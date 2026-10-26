using System.Globalization;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace AutoSolid.SolidWorksAgent;

internal sealed record VerificationResult(
    string Status,
    string Path,
    string Revision,
    bool RebuildSucceeded,
    double VolumeM3,
    double? ExpectedVolumeM3,
    double? VolumeDifferenceM3,
    int Errors,
    int Warnings,
    string Units,
    double[] BoundingBox);

internal sealed class SolidWorksBuilder
{
    public VerificationResult Build(CadSpecDocument spec, string outputPath)
    {
        var application = Connect();
        var template = application.GetUserPreferenceStringValue(
            (int)swUserPreferenceStringValue_e.swDefaultTemplatePart);
        if (string.IsNullOrWhiteSpace(template) || !File.Exists(template))
        {
            throw new InvalidOperationException("No se encontró la plantilla de parte configurada.");
        }

        var document = (IModelDoc2?)application.NewDocument(template, 0, 0, 0)
            ?? throw new InvalidOperationException("SolidWorks no creó el documento.");
        SelectFrontPlane(document);
        document.SketchManager.InsertSketch(true);
        var segments = new Dictionary<string, ISketchSegment>();
        foreach (var entity in spec.Entities)
        {
            var segment = document.SketchManager.CreateLine(
                entity.Start.X / 1000.0,
                entity.Start.Y / 1000.0,
                0.0,
                entity.End.X / 1000.0,
                entity.End.Y / 1000.0,
                0.0)
                ?? throw new InvalidOperationException($"No se creó la línea {entity.Id}.");
            segments.Add(entity.Id, segment);
        }
        if (spec.AxisEntityId is not null)
        {
            segments[spec.AxisEntityId].ConstructionGeometry = true;
        }
        document.SketchManager.InsertSketch(true);

        Feature? feature;
        if (spec.FeatureKind == "extrude")
        {
            feature = document.FeatureManager.FeatureExtrusion2(
                true, false, false, 0, 0, spec.DistanceMeters, 0.0,
                false, false, false, false, 0.0, 0.0,
                false, false, false, false, false, false, true, 0, 0.0, false);
        }
        else
        {
            if (!SelectLastSketch(document))
            {
                throw new InvalidOperationException("No se pudo seleccionar el croquis de revolución.");
            }
            var axis = segments[spec.AxisEntityId!];
            if (!axis.Select4(true, null))
            {
                throw new InvalidOperationException("No se pudo seleccionar el eje de revolución.");
            }
            feature = document.FeatureManager.FeatureRevolve(
                spec.AngleRadians, false, 0.0, 0, 0, true, false, false);
        }

        if (feature is null)
        {
            throw new InvalidOperationException("SolidWorks no creó la operación.");
        }
        if (!document.EditRebuild3())
        {
            throw new InvalidOperationException("La reconstrucción de la pieza falló.");
        }
        int errors = 0;
        int warnings = 0;
        if (!document.SaveAs4(outputPath, 0, 0, ref errors, ref warnings) || errors != 0)
        {
            throw new InvalidOperationException($"SaveAs4 falló con código {errors}.");
        }
        if (!File.Exists(outputPath))
        {
            throw new InvalidOperationException("SaveAs4 no generó el archivo esperado.");
        }
        return Inspect(
            document,
            outputPath,
            application.RevisionNumber(),
            spec.ExpectedVolumeM3,
            errors,
            warnings);
    }

    public VerificationResult Verify(string path)
    {
        var application = Connect();
        int errors = 0;
        int warnings = 0;
        var document = application.OpenDoc6(
            path,
            (int)swDocumentTypes_e.swDocPART,
            (int)swOpenDocOptions_e.swOpenDocOptions_Silent,
            string.Empty,
            ref errors,
            ref warnings)
            ?? throw new InvalidOperationException($"OpenDoc6 falló con código {errors}.");
        return Inspect(
            document,
            path,
            application.RevisionNumber(),
            null,
            errors,
            warnings);
    }

    private static VerificationResult Inspect(
        IModelDoc2 document,
        string path,
        string revision,
        double? expectedVolume,
        int errors,
        int warnings)
    {
        var rebuilt = document.EditRebuild3();
        var properties = (Array?)document.GetMassProperties()
            ?? throw new InvalidOperationException("No se pudieron obtener propiedades de masa.");
        if (properties.Length < 4)
        {
            throw new InvalidOperationException("GetMassProperties no devolvió volumen.");
        }
        var volume = Convert.ToDouble(
            properties.GetValue(3),
            CultureInfo.InvariantCulture);
        var difference = expectedVolume is null
            ? (double?)null
            : Math.Abs(volume - expectedVolume.Value);
        if (difference is not null && difference > 1e-9)
        {
            throw new InvalidOperationException(
                $"Volumen inesperado: {volume} m³; esperado {expectedVolume} m³.");
        }
        var unitValues = (Array?)document.GetUnits()
            ?? throw new InvalidOperationException("No se pudieron leer las unidades.");
        var units = string.Join(",", unitValues.Cast<object>());
        var boxValues = (Array?)((IPartDoc)document).GetPartBox(false)
            ?? throw new InvalidOperationException("No se pudo leer el bounding box.");
        var boundingBox = boxValues.Cast<object>()
            .Select(value => Convert.ToDouble(value, CultureInfo.InvariantCulture))
            .ToArray();
        return new VerificationResult(
            rebuilt ? "ok" : "rebuild_failed",
            path,
            revision,
            rebuilt,
            volume,
            expectedVolume,
            difference,
            errors,
            warnings,
            units,
            boundingBox);
    }

    private static bool SelectLastSketch(IModelDoc2 document)
    {
        Feature? lastSketch = null;
        var featureTypes = new List<string>();
        var feature = (Feature?)document.FirstFeature();
        while (feature is not null)
        {
            var type = feature.GetTypeName2();
            featureTypes.Add($"{feature.Name}:{type}");
            if (type is "Sketch" or "ProfileFeature")
            {
                lastSketch = feature;
            }
            feature = (Feature?)feature.GetNextFeature();
        }
        if (lastSketch is null)
        {
            throw new InvalidOperationException(
                $"No hay croquis en el árbol: {string.Join(", ", featureTypes)}");
        }
        if (!lastSketch.Select2(false, 0))
        {
            throw new InvalidOperationException(
                $"Select2 falló para {lastSketch.Name}: {string.Join(", ", featureTypes)}");
        }
        return true;
    }

    private static ISldWorks Connect()
    {
        var applicationType = Type.GetTypeFromProgID("SldWorks.Application")
            ?? throw new InvalidOperationException("SolidWorks ProgID no está registrado.");
        var application = (ISldWorks?)Activator.CreateInstance(applicationType)
            ?? throw new InvalidOperationException("No se pudo iniciar SolidWorks.");
        application.Visible = true;
        return application;
    }

    private static void SelectFrontPlane(IModelDoc2 document)
    {
        var names = new List<string>
        {
            "Front Plane", "Plano alzado", "Plano frontal", "Plano de referencia frontal",
        };
        var feature = (Feature?)document.FirstFeature();
        while (feature is not null)
        {
            if (feature.GetTypeName2() == "RefPlane")
            {
                names.Add(feature.Name);
            }
            feature = (Feature?)feature.GetNextFeature();
        }
        if (!names.Distinct().Any(name => document.Extension.SelectByID2(
            name, "PLANE", 0, 0, 0, false, 0, null, 0)))
        {
            throw new InvalidOperationException(
                "No se encontró el plano frontal en la plantilla configurada.");
        }
    }
}
