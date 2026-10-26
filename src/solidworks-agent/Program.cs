using System.Text.Json;
using AutoSolid.SolidWorksAgent;
using SolidWorks.Interop.sldworks;

var jsonOptions = new JsonSerializerOptions
{
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    WriteIndented = false,
};

try
{
    if (args.Length == 1 && args[0] == "version")
    {
        var applicationType = Type.GetTypeFromProgID("SldWorks.Application")
            ?? throw new InvalidOperationException("SolidWorks ProgID no está registrado.");
        var application = (ISldWorks?)Activator.CreateInstance(applicationType)
            ?? throw new InvalidOperationException("No se pudo iniciar SolidWorks.");
        application.Visible = true;
        Console.WriteLine(JsonSerializer.Serialize(new
        {
            status = "ok",
            revision = application.RevisionNumber(),
        }, jsonOptions));
        return 0;
    }

    if (args.Length == 3 && args[0] == "build")
    {
        var spec = CadSpecDocument.Load(args[1]);
        var outputPath = CadSpecDocument.NewPartPath(args[2]);
        var result = new SolidWorksBuilder().Build(spec, outputPath);
        Console.WriteLine(JsonSerializer.Serialize(result, jsonOptions));
        return result.RebuildSucceeded ? 0 : 1;
    }

    if (args.Length == 2 && args[0] == "verify")
    {
        var path = Path.GetFullPath(args[1]);
        if (!File.Exists(path))
        {
            throw new InvalidDataException("El SLDPRT no existe.");
        }
        var result = new SolidWorksBuilder().Verify(path);
        Console.WriteLine(JsonSerializer.Serialize(result, jsonOptions));
        return result.RebuildSucceeded ? 0 : 1;
    }

    Console.Error.WriteLine(
        "Uso: autosolid-solidworks version | build <spec.json> <output.sldprt> | verify <output.sldprt>");
    return 2;
}
catch (Exception error) when (
    error is InvalidDataException
    or InvalidOperationException
    or IOException
    or UnauthorizedAccessException
    or System.Runtime.InteropServices.COMException)
{
    Console.Error.WriteLine(JsonSerializer.Serialize(new
    {
        status = "error",
        error = error.GetType().Name,
        message = error.Message,
    }, jsonOptions));
    return 1;
}
