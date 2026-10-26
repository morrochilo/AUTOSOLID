"""Run the configured SolidWorks C# agent without a shell.

The runner never receives a command from a model or from an HTTP caller. It
builds a fixed argument list (``build <spec> <output>``), captures bounded
stdout/stderr, enforces a timeout and validates the JSON contract emitted by
``src/solidworks-agent``.
"""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024
DEFAULT_VOLUME_TOLERANCE_M3 = 1e-9


class BuildExecutionError(Exception):
    """Stable, non-sensitive failure raised by a build runner."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BuildExecutionResult:
    revision: str | None
    volume_m3: float
    expected_volume_m3: float | None
    volume_difference_m3: float
    errors: int
    warnings: int


class SolidWorksRunner(Protocol):
    def build(
        self,
        spec_path: Path,
        output_path: Path,
        *,
        output_root: Path,
    ) -> BuildExecutionResult: ...


class UnavailableSolidWorksRunner:
    """Fails every build with a stable code when no agent is configured."""

    def build(
        self,
        spec_path: Path,
        output_path: Path,
        *,
        output_root: Path,
    ) -> BuildExecutionResult:
        raise BuildExecutionError(
            "SOLIDWORKS_NOT_CONFIGURED",
            "No hay un ejecutable del agente SolidWorks configurado.",
        )


class _BoundedReader(threading.Thread):
    def __init__(self, stream, limit: int) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self.data = bytearray()
        self.truncated = False

    def run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(4096)
                if not chunk:
                    return
                remaining = self._limit - len(self.data)
                if remaining > 0:
                    self.data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.truncated = True
                if len(self.data) >= self._limit:
                    self.truncated = self.truncated or bool(
                        self._stream.read(1)
                    )
                    # Keep draining without retaining more bytes.
                    while self._stream.read(4096):
                        pass
                    return
        except (OSError, ValueError):
            return


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Best-effort stop of the agent process tree.

    On POSIX the child is started in its own session and the whole group is
    killed. On Windows ``taskkill /T`` only targets descendants of this PID; an
    independently running SolidWorks instance is not a descendant and is not
    touched. If the platform cannot stop a descendant, the direct child is
    still killed and the timeout remains a failure.
    """

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=10,
                check=False,
            )
            return
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            process.kill()
        except OSError:  # pragma: no cover - defensive
            pass
        return

    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:  # pragma: no cover - defensive
            pass


class SubprocessSolidWorksRunner:
    """Execute the C# agent through :class:`subprocess.Popen` without a shell."""

    def __init__(
        self,
        executable: str | os.PathLike[str],
        *,
        arguments_prefix: Sequence[str] = (),
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        volume_tolerance_m3: float = DEFAULT_VOLUME_TOLERANCE_M3,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(executable, (str, os.PathLike)):
            raise ValueError("El ejecutable debe ser una ruta.")
        executable_text = os.fspath(executable)
        if not executable_text or "\x00" in executable_text:
            raise ValueError("La ruta del ejecutable no es válida.")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("El timeout debe ser un número positivo.")
        if (
            isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or max_output_bytes < 1024
        ):
            raise ValueError("El límite de salida debe ser al menos 1024 bytes.")
        if (
            isinstance(volume_tolerance_m3, bool)
            or not isinstance(volume_tolerance_m3, (int, float))
            or not math.isfinite(float(volume_tolerance_m3))
            or volume_tolerance_m3 < 0
        ):
            raise ValueError("La tolerancia de volumen no es válida.")

        self._executable = executable_text
        self._arguments_prefix = tuple(str(argument) for argument in arguments_prefix)
        if any("\x00" in argument for argument in self._arguments_prefix):
            raise ValueError("Los argumentos del ejecutable no son válidos.")
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_bytes = max_output_bytes
        self.volume_tolerance_m3 = float(volume_tolerance_m3)
        self._environment = (
            None if environment is None else dict(environment)
        )

    def build(
        self,
        spec_path: Path,
        output_path: Path,
        *,
        output_root: Path,
    ) -> BuildExecutionResult:
        resolved_root = Path(output_root).expanduser().resolve()
        raw_output = Path(output_path).expanduser()
        resolved_output = raw_output.resolve()
        resolved_spec = Path(spec_path).expanduser().resolve()

        if raw_output.is_symlink():
            raise BuildExecutionError(
                "OUTPUT_INVALID",
                "La salida del agente no puede ser un enlace simbólico.",
            )
        if not resolved_output.is_relative_to(resolved_root):
            raise BuildExecutionError(
                "OUTPUT_OUTSIDE_ROOT",
                "La salida del agente no pertenece al directorio autorizado.",
            )
        if resolved_output == resolved_root:
            raise BuildExecutionError(
                "OUTPUT_OUTSIDE_ROOT",
                "La salida del agente no es un archivo autorizado.",
            )
        if not str(resolved_output).lower().endswith(".sldprt"):
            raise BuildExecutionError(
                "OUTPUT_INVALID",
                "La salida del agente debe ser un archivo .sldprt.",
            )
        if resolved_output.exists():
            raise BuildExecutionError(
                "DESTINATION_EXISTS",
                "La salida ya existe; no se sobrescribe.",
            )
        if not resolved_spec.is_file():
            raise BuildExecutionError(
                "SPEC_MISSING",
                "La especificación temporal del trabajo no está disponible.",
            )

        executable = self._resolve_executable()
        command = [
            executable,
            *self._arguments_prefix,
            "build",
            str(resolved_spec),
            str(resolved_output),
        ]
        environment = None
        if self._environment is not None:
            environment = os.environ.copy()
            environment.update(self._environment)

        try:
            resolved_output.parent.mkdir(parents=True, exist_ok=True)
            popen_kwargs: dict[str, object] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "shell": False,
                "cwd": str(resolved_root),
                "env": environment,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                popen_kwargs["start_new_session"] = True
            process = subprocess.Popen(command, **popen_kwargs)
        except OSError as error:
            raise BuildExecutionError(
                "SOLIDWORKS_NOT_CONFIGURED",
                "No se pudo iniciar el agente SolidWorks configurado.",
            ) from error

        stdout_reader = _BoundedReader(process.stdout, self.max_output_bytes)
        stderr_reader = _BoundedReader(process.stderr, self.max_output_bytes)
        stdout_reader.start()
        stderr_reader.start()

        timed_out = False
        try:
            return_code = process.wait(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_tree(process)
            try:
                return_code = process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                try:
                    process.kill()
                except OSError:
                    pass
                return_code = process.wait()

        stdout_reader.join(timeout=5.0)
        stderr_reader.join(timeout=5.0)
        try:
            process.stdout.close()
        except (OSError, ValueError):  # pragma: no cover - defensive
            pass
        try:
            process.stderr.close()
        except (OSError, ValueError):  # pragma: no cover - defensive
            pass

        if timed_out:
            raise BuildExecutionError(
                "RUNNER_TIMEOUT",
                "El agente SolidWorks superó el tiempo máximo de ejecución.",
            )

        stdout_bytes = bytes(stdout_reader.data)
        if stdout_reader.truncated:
            raise BuildExecutionError(
                "RUNNER_OUTPUT_TOO_LARGE",
                "La salida del agente SolidWorks supera el límite permitido.",
            )

        payload: object | None = None
        if stdout_bytes:
            try:
                payload = json.loads(stdout_bytes.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                payload = None

        if not isinstance(payload, dict):
            code = "RUNNER_EXIT" if return_code != 0 else "RUNNER_OUTPUT_INVALID"
            raise BuildExecutionError(
                code,
                "El agente SolidWorks no devolvió un resultado válido.",
            )

        if payload.get("status") != "ok":
            raise BuildExecutionError(
                "RUNNER_REBUILD_FAILED",
                "SolidWorks no completó la reconstrucción correctamente.",
            )
        if payload.get("rebuildSucceeded") is not True:
            raise BuildExecutionError(
                "RUNNER_REBUILD_FAILED",
                "SolidWorks no confirmó una reconstrucción correcta.",
            )
        if return_code != 0:
            raise BuildExecutionError(
                "RUNNER_EXIT",
                "El agente SolidWorks terminó con un código de error.",
            )

        errors = payload.get("errors")
        if (
            isinstance(errors, bool)
            or not isinstance(errors, int)
            or errors != 0
        ):
            raise BuildExecutionError(
                "RUNNER_OUTPUT_INVALID",
                "El resultado del agente declara errores de reconstrucción.",
            )

        volume = _finite_number(payload.get("volumeM3"))
        difference = _finite_number(payload.get("volumeDifferenceM3"))
        expected = payload.get("expectedVolumeM3")
        expected_volume = None if expected is None else _finite_number(expected)
        warnings = payload.get("warnings", 0)
        if isinstance(warnings, bool) or not isinstance(warnings, int):
            raise BuildExecutionError(
                "RUNNER_OUTPUT_INVALID",
                "El resultado del agente no contiene advertencias válidas.",
            )
        if volume < 0:
            raise BuildExecutionError(
                "RUNNER_OUTPUT_INVALID",
                "El resultado del agente contiene un volumen negativo.",
            )
        if abs(difference) > self.volume_tolerance_m3:
            raise BuildExecutionError(
                "VOLUME_MISMATCH",
                "La diferencia de volumen supera la tolerancia permitida.",
            )
        if (
            expected_volume is not None
            and abs(volume - expected_volume) > self.volume_tolerance_m3
        ):
            raise BuildExecutionError(
                "VOLUME_MISMATCH",
                "El volumen medido no coincide con el volumen esperado.",
            )

        if not resolved_output.is_file():
            raise BuildExecutionError(
                "OUTPUT_MISSING",
                "El agente no generó el archivo .sldprt esperado.",
            )
        if resolved_output.stat().st_size <= 0:
            raise BuildExecutionError(
                "OUTPUT_MISSING",
                "El archivo .sldprt generado está vacío.",
            )

        revision = payload.get("revision")
        return BuildExecutionResult(
            revision=revision if isinstance(revision, str) else None,
            volume_m3=volume,
            expected_volume_m3=expected_volume,
            volume_difference_m3=difference,
            errors=errors,
            warnings=warnings,
        )

    def _resolve_executable(self) -> str:
        candidate = Path(self._executable).expanduser()
        if candidate.is_absolute() or candidate.parent != Path("."):
            resolved = candidate.resolve()
            if not resolved.is_file():
                raise BuildExecutionError(
                    "SOLIDWORKS_NOT_CONFIGURED",
                    "El ejecutable del agente SolidWorks no existe.",
                )
            return str(resolved)
        if os.sep in self._executable or (
            os.altsep is not None and os.altsep in self._executable
        ):
            resolved = candidate.resolve()
            if not resolved.is_file():
                raise BuildExecutionError(
                    "SOLIDWORKS_NOT_CONFIGURED",
                    "El ejecutable del agente SolidWorks no existe.",
                )
            return str(resolved)
        return self._executable


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BuildExecutionError(
            "RUNNER_OUTPUT_INVALID",
            "El resultado del agente no contiene números válidos.",
        )
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise BuildExecutionError(
            "RUNNER_OUTPUT_INVALID",
            "El resultado del agente contiene valores fuera de rango.",
        ) from error
    if not math.isfinite(result):
        raise BuildExecutionError(
            "RUNNER_OUTPUT_INVALID",
            "El resultado del agente contiene valores no finitos.",
        )
    return result
