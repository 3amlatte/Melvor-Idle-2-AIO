using System.IO.Compression;

if (args.Length != 2)
{
    Console.Error.WriteLine("usage: SaveTool <input.sav> <output.raw>");
    return 2;
}

string inputPath = args[0];
string outputPath = args[1];

try
{
    using FileStream input = File.OpenRead(inputPath);
    using BrotliStream brotli = new(input, CompressionMode.Decompress);
    using FileStream output = File.Create(outputPath);
    brotli.CopyTo(output);
    Console.WriteLine(output.Length);
    return 0;
}
catch (Exception ex)
{
    Console.Error.WriteLine($"SaveTool failed: {ex.Message}");
    return 1;
}
