using System.Diagnostics;
using System.Numerics;
using System.Reflection;
using System.Security.Cryptography;
using ImGuiNET;
using NativeFileDialogNET;
using RecompOne.Runtime.Host;

namespace RecompOne.Runtime.Cdrom;

public sealed record DiscInstallProfile(
    string WindowTitle,
    string CommonName,
    string DiscId,
    string BootFile,
    int BootFileSize,
    string BootSha256,
    string SystemCnfSha256,
    int LeadoutLba,
    string BundledAssetResource);

/// <summary>
/// Exact, content-based identification of the supported retail revision. The boot and
/// SYSTEM.CNF hashes make the result independent of a user's dump filename, while the
/// lead-out rejects partial or rebuilt images that happen to contain those two files.
/// </summary>
public static class DiscRevisionValidator
{
    public static string? Validate(string path, DiscInstallProfile profile)
    {
        try
        {
            using var fs = DiscFs.Open(path);
            if (!fs.Locate(profile.BootFile, out _, out uint bootSize))
                return Required(profile, $"{profile.BootFile} was not found");
            if (bootSize != profile.BootFileSize)
                return Required(profile, $"{profile.BootFile} has the wrong size ({bootSize:N0} bytes)");
            if (!Hash(fs.ReadFile(profile.BootFile)).Equals(profile.BootSha256, StringComparison.OrdinalIgnoreCase))
                return Required(profile, $"{profile.BootFile} belongs to a different revision");
            if (!fs.Exists("SYSTEM.CNF") ||
                !Hash(fs.ReadFile("SYSTEM.CNF")).Equals(profile.SystemCnfSha256, StringComparison.OrdinalIgnoreCase))
                return Required(profile, "SYSTEM.CNF belongs to a different revision");
            if (fs.LeadoutLba != profile.LeadoutLba)
                return Required(profile, $"disc length is {fs.LeadoutLba:N0} sectors, expected {profile.LeadoutLba:N0}");
            return null;
        }
        catch (Exception e)
        {
            return Required(profile, e.Message);
        }
    }

    static string Required(DiscInstallProfile profile, string problem) =>
        $"{problem}. Select {profile.CommonName} [{profile.DiscId}] as a BIN/CUE dump.";

    static string Hash(byte[] data) => Convert.ToHexString(SHA256.HashData(data));
}

/// <summary>
/// First-run installer hosted by the runtime's existing ImGui window. Extraction runs
/// on a worker thread while the render thread continues to pump events and draw elapsed
/// time plus byte-accurate progress. No shell or helper process is launched.
/// </summary>
public static class FirstRunDiscInstaller
{
    static readonly object Gate = new();
    static Session? _session;

    public static string EnsureInstalled(
        DiscInstallProfile profile,
        string outputDirectory,
        string? existingLooseDirectory,
        string? requestedImage,
        Assembly payloadAssembly)
    {
        string output = Path.GetFullPath(outputDirectory);
        Runtime.DiscValidator = path => DiscRevisionValidator.Validate(path, profile);
        string? existing = ValidLoose(output, profile) ?? ValidLoose(existingLooseDirectory, profile);
        if (existing != null)
        {
            InstallBundledAssets(payloadAssembly, profile, Path.GetDirectoryName(output)!);
            return existing;
        }

        if (string.Equals(
            Environment.GetEnvironmentVariable("RECOMP_INSTALL_HEADLESS"), "1",
            StringComparison.Ordinal))
        {
            if (string.IsNullOrWhiteSpace(requestedImage))
                throw new InvalidOperationException(
                    $"No loose installation exists. Pass the CUE for {profile.CommonName} [{profile.DiscId}].");
            string? error = DiscRevisionValidator.Validate(requestedImage, profile);
            if (error != null) throw new InvalidDataException(error);
            string imported = LooseDiscImporter.Import(requestedImage, output, profile.DiscId);
            InstallBundledAssets(payloadAssembly, profile, Path.GetDirectoryName(output)!);
            return imported;
        }

        HostWindow.SuppressAutomaticDiscPicker = true;
        Runtime.Initialize(profile.WindowTitle);

        if (HostWindow.IsHeadless)
        {
            if (string.IsNullOrWhiteSpace(requestedImage))
                throw new InvalidOperationException(
                    $"No loose installation exists. Pass the CUE for {profile.CommonName} [{profile.DiscId}].");
            string? error = DiscRevisionValidator.Validate(requestedImage, profile);
            if (error != null) throw new InvalidDataException(error);
            string imported = LooseDiscImporter.Import(requestedImage, output, profile.DiscId);
            InstallBundledAssets(payloadAssembly, profile, Path.GetDirectoryName(output)!);
            return imported;
        }

        var session = new Session(profile, output, payloadAssembly, requestedImage);
        lock (Gate) _session = session;
        try
        {
            while (!session.Finished) HostWindow.Pump();
            if (session.Error != null) throw new InvalidOperationException(session.Error);
            return session.Result!;
        }
        finally
        {
            lock (Gate) _session = null;
        }
    }

    static string? ValidLoose(string? candidate, DiscInstallProfile profile)
    {
        if (string.IsNullOrWhiteSpace(candidate) || !LooseDiscImage.IsLooseDirectory(candidate)) return null;
        return DiscRevisionValidator.Validate(candidate, profile) == null ? Path.GetFullPath(candidate) : null;
    }

    internal static void Draw()
    {
        Session? session;
        lock (Gate) session = _session;
        session?.Draw();
    }

    static void InstallBundledAssets(Assembly assembly, DiscInstallProfile profile, string installRoot)
    {
        string target = Path.Combine(installRoot, "assets", "builtin");
        using Stream? payload = assembly.GetManifestResourceStream(profile.BundledAssetResource);
        if (payload == null)
            throw new InvalidOperationException(
                $"embedded bundled-content payload is missing: {profile.BundledAssetResource}");
        BundledAssets.Extract(payload, target, null, CancellationToken.None);
    }

    sealed class Session
    {
        readonly DiscInstallProfile _profile;
        readonly string _output;
        readonly Assembly _assembly;
        readonly Stopwatch _elapsed = Stopwatch.StartNew();
        readonly object _stateGate = new();
        string _path;
        string _stage = "Waiting for disc image";
        string _currentFile = "";
        string _error = "";
        long _completedBytes;
        long _totalBytes;
        int _completedFiles;
        int _totalFiles;
        Task? _task;

        public Session(
            DiscInstallProfile profile,
            string output,
            Assembly assembly,
            string? requestedImage)
        {
            _profile = profile;
            _output = output;
            _assembly = assembly;
            _path = requestedImage ?? "";
            if (_path.Length > 0) Start();
        }

        int _finished;
        public bool Finished => Volatile.Read(ref _finished) != 0;
        public string? Result { get; private set; }
        public string? Error { get; private set; }

        public void Draw()
        {
            var viewport = ImGui.GetMainViewport();
            ImGui.SetNextWindowPos(viewport.WorkPos);
            ImGui.SetNextWindowSize(viewport.WorkSize);
            const ImGuiWindowFlags flags =
                ImGuiWindowFlags.NoDecoration | ImGuiWindowFlags.NoMove |
                ImGuiWindowFlags.NoSavedSettings | ImGuiWindowFlags.NoDocking;
            ImGui.Begin("##first-run-disc-installer", flags);

            float width = MathF.Min(680f, ImGui.GetContentRegionAvail().X - 40f);
            float left = MathF.Max(20f, (ImGui.GetContentRegionAvail().X - width) * 0.5f);
            ImGui.SetCursorPosX(left);
            ImGui.BeginGroup();
            ImGui.Dummy(new Vector2(0f, MathF.Max(24f, viewport.WorkSize.Y * 0.13f)));
            ImGui.TextUnformatted(_profile.WindowTitle);
            ImGui.Separator();
            ImGui.Spacing();
            ImGui.TextWrapped("First-time setup needs your original game dump. This is a one-time extraction; the BIN/CUE is not used after setup.");
            ImGui.Spacing();
            ImGui.TextUnformatted("Required disc:");
            ImGui.BulletText(_profile.CommonName);
            ImGui.BulletText($"Disc ID: {_profile.DiscId}");
            ImGui.Spacing();

            if (_task == null)
            {
                float browseWidth = 110f;
                float spacing = ImGui.GetStyle().ItemSpacing.X;
                ImGui.SetNextItemWidth(width - browseWidth - spacing);
                ImGui.InputText("##install-cue-path", ref _path, 2048);
                ImGui.SameLine();
                if (ImGui.Button("Browse...", new Vector2(browseWidth, 0f))) Browse();
                ImGui.Spacing();
                if (_error.Length > 0)
                {
                    ImGui.PushStyleColor(ImGuiCol.Text, new Vector4(1f, 0.38f, 0.38f, 1f));
                    ImGui.TextWrapped(_error);
                    ImGui.PopStyleColor();
                    ImGui.Spacing();
                }
                bool validPath = File.Exists(_path);
                if (!validPath) ImGui.BeginDisabled();
                if (ImGui.Button("Validate and extract", new Vector2(width, 34f))) Start();
                if (!validPath) ImGui.EndDisabled();
            }
            else
            {
                string stage;
                string current;
                long completed;
                long total;
                int files;
                int fileTotal;
                lock (_stateGate)
                {
                    stage = _stage;
                    current = _currentFile;
                    completed = _completedBytes;
                    total = _totalBytes;
                    files = _completedFiles;
                    fileTotal = _totalFiles;
                }
                float fraction = total <= 0 ? 0f : Math.Clamp((float)completed / total, 0f, 1f);
                ImGui.TextUnformatted(stage);
                ImGui.ProgressBar(fraction, new Vector2(width, 28f), $"{fraction * 100f:0.0}%");
                ImGui.TextUnformatted($"Elapsed: {_elapsed.Elapsed:hh\\:mm\\:ss}");
                if (fileTotal > 0) ImGui.TextUnformatted($"Files: {files:N0} / {fileTotal:N0}");
                if (current.Length > 0) ImGui.TextWrapped(current);
            }

            ImGui.EndGroup();
            ImGui.End();
        }

        void Browse()
        {
            try
            {
                string? directory = File.Exists(_path) ? Path.GetDirectoryName(Path.GetFullPath(_path)) : null;
                using var dialog = new NativeFileDialog().SelectFile().AddFilter("PlayStation CUE sheet", "cue");
                if (dialog.Open(out string? picked, directory) == DialogResult.Okay && !string.IsNullOrWhiteSpace(picked))
                {
                    _path = picked;
                    _error = "";
                }
            }
            catch (Exception e)
            {
                _error = e.Message;
            }
        }

        void Start()
        {
            string image = _path.Trim();
            string? problem = DiscRevisionValidator.Validate(image, _profile);
            if (problem != null)
            {
                _error = problem;
                _task = null;
                return;
            }

            _error = "";
            _elapsed.Restart();
            var progress = new InlineProgress<LooseDiscImporter.Progress>(value =>
            {
                lock (_stateGate)
                {
                    _stage = value.Stage;
                    _currentFile = value.CurrentFile;
                    _completedFiles = value.FilesCompleted;
                    _totalFiles = value.TotalFiles;
                    _completedBytes = value.BytesCompleted;
                    _totalBytes = value.TotalBytes;
                }
            });

            _task = Task.Run(() =>
            {
                try
                {
                    string result = LooseDiscImporter.Import(
                        image, _output, _profile.DiscId, progress, CancellationToken.None);
                    lock (_stateGate)
                    {
                        _stage = "Installing bundled upgrades";
                        _currentFile = "";
                    }
                    using Stream? payload = _assembly.GetManifestResourceStream(_profile.BundledAssetResource);
                    if (payload == null)
                        throw new InvalidOperationException(
                            $"embedded bundled-content payload is missing: {_profile.BundledAssetResource}");
                    BundledAssets.Extract(payload, Path.Combine(Path.GetDirectoryName(_output)!, "assets", "builtin"), null, CancellationToken.None);
                    Result = result;
                    Volatile.Write(ref _finished, 1);
                }
                catch (Exception e)
                {
                    Error = e.Message;
                    _error = e.Message;
                    _task = null;
                }
            });
        }
    }

    sealed class InlineProgress<T>(Action<T> action) : IProgress<T>
    {
        public void Report(T value) => action(value);
    }
}
