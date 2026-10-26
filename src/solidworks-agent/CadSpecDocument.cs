using System.Globalization;
using System.Text.Json;

namespace AutoSolid.SolidWorksAgent;

internal sealed record Point2(double X, double Y)
{
    public static Point2 operator -(Point2 a, Point2 b) => new(a.X - b.X, a.Y - b.Y);
}

internal sealed record LineEntity(string Id, Point2 Start, Point2 End);

internal sealed class CadSpecDocument
{
    public required string ProjectId { get; init; }
    public required string FeatureKind { get; init; }
    public required List<LineEntity> Entities { get; init; }
    public required double DistanceMeters { get; init; }
    public required double AngleRadians { get; init; }
    public string? AxisEntityId { get; init; }
    public required double ExpectedVolumeM3 { get; init; }

    public static CadSpecDocument Load(string path)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var root = document.RootElement;
        Require(root.GetProperty("schema_version").GetString() == "0.1.0", "schema_version no soportada");
        Require(root.GetProperty("project_id").GetString() is { Length: > 0 }, "project_id vacío");
        Require(root.GetProperty("units").GetProperty("length").GetString() == "mm", "Solo unidades mm");
        Require(root.GetProperty("units").GetProperty("angle").GetString() == "deg", "Solo ángulos deg");

        if (root.GetProperty("open_questions").EnumerateArray().Any(question =>
            question.GetProperty("severity").GetString() == "critical" &&
            question.GetProperty("status").GetString() == "open"))
        {
            throw new InvalidDataException("Hay preguntas críticas abiertas");
        }

        var sketches = root.GetProperty("sketches").EnumerateArray().ToList();
        Require(sketches.Count == 1, "Se requiere exactamente un croquis");
        var entities = sketches[0].GetProperty("entities").EnumerateArray().Select(entity =>
        {
            var id = entity.GetProperty("id").GetString() ?? throw Error("Entidad sin id");
            Require(entity.GetProperty("kind").GetString() == "line", $"Entidad no soportada: {id}");
            return new LineEntity(id, Point(entity.GetProperty("start")), Point(entity.GetProperty("end")));
        }).ToList();
        Require(entities.Count >= 3, "El croquis necesita al menos tres líneas");
        Require(entities.All(entity => Distance(entity.Start, entity.End) > 1e-12), "Hay líneas de longitud cero");
        ValidateClosedLoop(entities);

        var features = root.GetProperty("features").EnumerateArray().ToList();
        Require(features.Count == 1, "Se requiere exactamente una operación");
        var feature = features[0];
        var kind = feature.GetProperty("kind").GetString() ?? throw Error("Operación sin kind");
        Require(feature.GetProperty("sketch_id").GetString() == sketches[0].GetProperty("id").GetString(), "sketch_id no coincide");
        Require(feature.GetProperty("operation").GetString() == "new_body", "Solo new_body");

        double distance = 0;
        double angle = 0;
        string? axisEntityId = null;
        if (kind == "extrude")
        {
            distance = DecimalDouble(feature.GetProperty("distance")) / 1000.0;
            Require(distance > 0 && double.IsFinite(distance), "Distancia inválida");
        }
        else if (kind == "revolve")
        {
            angle = DecimalDouble(feature.GetProperty("angle")) * Math.PI / 180.0;
            Require(angle > 0 && angle <= 2 * Math.PI + 1e-12, "Ángulo inválido");
            var axisId = feature.GetProperty("axis_id").GetString() ?? throw Error("Falta axis_id");
            var constraints = sketches[0].GetProperty("constraints").EnumerateArray();
            axisEntityId = constraints
                .Where(item => item.GetProperty("kind").GetString() == "coincident_axis")
                .Where(item => item.GetProperty("reference_id").GetString() == axisId)
                .Select(item => item.GetProperty("entity_id").GetString())
                .SingleOrDefault()
                ?? throw Error("No hay un segmento coincidente con el eje");
            Require(entities.Any(entity => entity.Id == axisEntityId), "El segmento de eje no existe");
        }
        else
        {
            throw Error($"Operación no soportada: {kind}");
        }

        var expectedVolume = kind == "extrude"
            ? PolygonArea(entities) * distance
            : RevolvedVolume(entities, angle);
        Require(expectedVolume > 0 && double.IsFinite(expectedVolume), "Volumen esperado inválido");
        return new CadSpecDocument
        {
            ProjectId = root.GetProperty("project_id").GetString()!,
            FeatureKind = kind,
            Entities = entities,
            DistanceMeters = distance,
            AngleRadians = angle,
            AxisEntityId = axisEntityId,
            ExpectedVolumeM3 = expectedVolume,
        };
    }

    public static string NewPartPath(string path)
    {
        Require(!string.IsNullOrWhiteSpace(path), "Ruta de salida vacía");
        var fullPath = Path.GetFullPath(path);
        Require(fullPath.EndsWith(".sldprt", StringComparison.OrdinalIgnoreCase), "La salida debe ser .sldprt");
        Require(!File.Exists(fullPath), "La salida ya existe; no se sobrescribe");
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath)
            ?? throw Error("Ruta de salida inválida"));
        return fullPath;
    }

    private static Point2 Point(JsonElement element)
    {
        var values = element.EnumerateArray().ToList();
        Require(values.Count == 2, "Punto 2D inválido");
        var x = DecimalDouble(values[0]);
        var y = DecimalDouble(values[1]);
        Require(double.IsFinite(x) && double.IsFinite(y), "Coordenada no finita");
        return new Point2(x, y);
    }

    private static double DecimalDouble(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.String && decimal.TryParse(
            element.GetString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var parsedString))
        {
            return (double)parsedString;
        }
        if (element.ValueKind == JsonValueKind.Number && element.TryGetDecimal(out var parsedNumber))
        {
            return (double)parsedNumber;
        }
        throw Error("Número inválido");
    }

    private static double Distance(Point2 a, Point2 b) => Math.Sqrt(Math.Pow(a.X - b.X, 2) + Math.Pow(a.Y - b.Y, 2));

    private static double PolygonArea(IReadOnlyList<LineEntity> entities)
    {
        var vertices = OrderedVertices(entities);
        var twiceArea = 0.0;
        for (var index = 0; index < vertices.Count; index++)
        {
            var current = vertices[index];
            var next = vertices[(index + 1) % vertices.Count];
            twiceArea += current.X * next.Y - next.X * current.Y;
        }
        return Math.Abs(twiceArea) * 0.5 / 1_000_000.0;
    }

    private static double RevolvedVolume(IReadOnlyList<LineEntity> entities, double angle)
    {
        var vertices = OrderedVertices(entities);
        var signedArea = 0.0;
        var moment = 0.0;
        for (var index = 0; index < vertices.Count; index++)
        {
            var current = vertices[index];
            var next = vertices[(index + 1) % vertices.Count];
            var cross = current.X * next.Y - next.X * current.Y;
            signedArea += cross;
            moment += (current.Y + next.Y) * cross;
        }
        var centroidY = moment / (3 * signedArea);
        return Math.Abs(signedArea * 0.5 * centroidY * angle) / 1_000_000_000.0;
    }

    private static List<Point2> OrderedVertices(IReadOnlyList<LineEntity> entities)
    {
        var remaining = entities.ToList();
        var vertices = new List<Point2> { remaining[0].Start, remaining[0].End };
        remaining.RemoveAt(0);
        while (remaining.Count > 0)
        {
            var index = remaining.FindIndex(entity =>
                Same(vertices[^1], entity.Start) || Same(vertices[^1], entity.End));
            Require(index >= 0, "Croquis desconectado");
            var next = remaining[index];
            vertices.Add(Same(vertices[^1], next.Start) ? next.End : next.Start);
            remaining.RemoveAt(index);
        }
        Require(Same(vertices[^1], vertices[0]), "Croquis abierto");
        vertices.RemoveAt(vertices.Count - 1);
        return vertices;
    }

    private static void ValidateClosedLoop(IReadOnlyList<LineEntity> entities)
    {
        var degrees = new Dictionary<Point2, int>();
        foreach (var entity in entities)
        {
            degrees[entity.Start] = degrees.GetValueOrDefault(entity.Start) + 1;
            degrees[entity.End] = degrees.GetValueOrDefault(entity.End) + 1;
        }
        Require(degrees.Values.All(value => value == 2), "Cada vértice debe tener grado dos");
        _ = OrderedVertices(entities);
    }

    private static bool Same(Point2 a, Point2 b) => Math.Abs(a.X - b.X) <= 1e-9 && Math.Abs(a.Y - b.Y) <= 1e-9;

    private static void Require(bool condition, string message)
    {
        if (!condition) throw Error(message);
    }

    private static InvalidDataException Error(string message) => new(message);
}
