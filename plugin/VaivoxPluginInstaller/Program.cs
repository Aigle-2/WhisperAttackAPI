using Microsoft.Win32;
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security;
using System.Text.RegularExpressions;

namespace VaivoxPluginInstaller
{
    internal static class Program
    {
        private const string AppFolderName = "VAIVOX";
        private const string PluginDllName = "VaivoxVAPlugin.dll";
        private const string VoiceAttackExeName = "VoiceAttack.exe";
        private const string VoiceAttackDllName = "VoiceAttack.dll";

        private static int Main(string[] args)
        {
            Console.Title = "VAIVOX VoiceAttack Plugin Installer";
            WriteHeader();

            try
            {
                string sourcePlugin = FindBundledPluginDll();
                if (sourcePlugin == null)
                {
                    return Fail(
                        "Could not find the bundled " + PluginDllName + ".",
                        "Run this installer from the extracted VAIVOX release folder.");
                }

                Console.WriteLine("Plugin source:");
                Console.WriteLine("  " + sourcePlugin);
                Console.WriteLine();

                List<InstallCandidate> candidates = DiscoverVoiceAttackInstalls(args);
                string voiceAttackDir = SelectVoiceAttackInstall(candidates);
                if (voiceAttackDir == null)
                {
                    return Fail(
                        "No VoiceAttack installation was selected.",
                        "You can also run this installer with the VoiceAttack folder path as an argument.");
                }

                if (!IsVoiceAttackInstall(voiceAttackDir))
                {
                    return Fail(
                        "The selected folder does not look like a VoiceAttack installation:",
                        voiceAttackDir);
                }

                WaitForVoiceAttackToClose();

                string targetDir = Path.Combine(voiceAttackDir, "Apps", AppFolderName);
                string targetPlugin = Path.Combine(targetDir, PluginDllName);

                Directory.CreateDirectory(targetDir);
                File.Copy(sourcePlugin, targetPlugin, overwrite: true);

                Console.ForegroundColor = ConsoleColor.Green;
                Console.WriteLine("Installed VAIVOX VoiceAttack plugin successfully.");
                Console.ResetColor();
                Console.WriteLine("Target:");
                Console.WriteLine("  " + targetPlugin);
                Console.WriteLine();
                Console.WriteLine("Restart VoiceAttack, then enable plugin support if it is not already enabled.");
                PauseIfInteractive();
                return 0;
            }
            catch (UnauthorizedAccessException ex)
            {
                return Fail(
                    "Windows refused access while installing the plugin.",
                    ex.Message,
                    "Close VoiceAttack and run this installer as administrator.");
            }
            catch (IOException ex)
            {
                return Fail(
                    "Could not copy the plugin DLL.",
                    ex.Message,
                    "Close VoiceAttack if it is running, then try again.");
            }
            catch (Exception ex)
            {
                return Fail("Unexpected installer error.", ex.Message);
            }
        }

        private static void WriteHeader()
        {
            Console.WriteLine("VAIVOX VoiceAttack Plugin Installer");
            Console.WriteLine("==================================");
            Console.WriteLine();
        }

        private static string FindBundledPluginDll()
        {
            string exeDir = AppDomain.CurrentDomain.BaseDirectory;
            string cwd = Directory.GetCurrentDirectory();
            string parentDir = Path.GetFullPath(Path.Combine(exeDir, ".."));

            string[] roots = UniqueExistingDirectories(new[]
            {
                exeDir,
                cwd,
                parentDir,
                Path.Combine(exeDir, "VoiceAttack"),
                Path.Combine(cwd, "VoiceAttack")
            });

            string[] relativePaths =
            {
                Path.Combine("VoiceAttack", "Apps", AppFolderName, PluginDllName),
                Path.Combine("Apps", AppFolderName, PluginDllName),
                Path.Combine(AppFolderName, PluginDllName),
                PluginDllName
            };

            foreach (string root in roots)
            {
                foreach (string relativePath in relativePaths)
                {
                    string candidate = Path.GetFullPath(Path.Combine(root, relativePath));
                    if (File.Exists(candidate))
                    {
                        return candidate;
                    }
                }
            }

            return null;
        }

        private static List<InstallCandidate> DiscoverVoiceAttackInstalls(string[] args)
        {
            List<InstallCandidate> candidates = new List<InstallCandidate>();

            AddArgumentCandidates(candidates, args);
            AddEnvironmentCandidate(candidates);
            AddRegistryCandidates(candidates);
            AddCommonPathCandidates(candidates);
            AddSteamCandidates(candidates);

            return candidates
                .Where(candidate => IsVoiceAttackInstall(candidate.Path))
                .GroupBy(candidate => NormalizeKey(candidate.Path), StringComparer.OrdinalIgnoreCase)
                .Select(group => group.OrderBy(candidate => candidate.Score).First())
                .OrderBy(candidate => candidate.Score)
                .ThenBy(candidate => candidate.Path, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }

        private static void AddArgumentCandidates(List<InstallCandidate> candidates, string[] args)
        {
            if (args == null || args.Length == 0)
            {
                return;
            }

            foreach (string arg in args)
            {
                if (string.IsNullOrWhiteSpace(arg))
                {
                    continue;
                }

                string path = arg;
                string prefix = "--voiceattack-dir=";
                if (arg.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                {
                    path = arg.Substring(prefix.Length);
                }

                AddCandidate(candidates, path, "command line", 0);
            }
        }

        private static void AddEnvironmentCandidate(List<InstallCandidate> candidates)
        {
            AddCandidate(candidates, Environment.GetEnvironmentVariable("VOICEATTACK_DIR"), "VOICEATTACK_DIR", 10);
        }

        private static void AddRegistryCandidates(List<InstallCandidate> candidates)
        {
            RegistryHive[] hives = { RegistryHive.CurrentUser, RegistryHive.LocalMachine };
            RegistryView[] views = { RegistryView.Registry64, RegistryView.Registry32 };

            foreach (RegistryHive hive in hives)
            {
                foreach (RegistryView view in views)
                {
                    try
                    {
                        using (RegistryKey baseKey = RegistryKey.OpenBaseKey(hive, view))
                        using (RegistryKey uninstall = baseKey.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"))
                        {
                            if (uninstall == null)
                            {
                                continue;
                            }

                            foreach (string subkeyName in uninstall.GetSubKeyNames())
                            {
                                using (RegistryKey subkey = uninstall.OpenSubKey(subkeyName))
                                {
                                    if (subkey == null)
                                    {
                                        continue;
                                    }

                                    string displayName = subkey.GetValue("DisplayName") as string;
                                    if (!LooksLikeVoiceAttackName(displayName))
                                    {
                                        continue;
                                    }

                                    AddCandidate(candidates, subkey.GetValue("InstallLocation") as string, "registry: " + displayName, 20);
                                    AddCandidate(candidates, DirectoryFromDisplayIcon(subkey.GetValue("DisplayIcon") as string), "registry icon: " + displayName, 21);
                                }
                            }
                        }
                    }
                    catch (SecurityException)
                    {
                    }
                    catch (UnauthorizedAccessException)
                    {
                    }
                    catch (IOException)
                    {
                    }
                }
            }
        }

        private static void AddCommonPathCandidates(List<InstallCandidate> candidates)
        {
            string[] roots = UniqueExistingDirectories(new[]
            {
                Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86)
            });

            foreach (string root in roots)
            {
                AddCandidate(candidates, Path.Combine(root, "VoiceAttack 2"), "Program Files", 30);
                AddCandidate(candidates, Path.Combine(root, "VoiceAttack"), "Program Files", 31);
            }
        }

        private static void AddSteamCandidates(List<InstallCandidate> candidates)
        {
            foreach (string steamRoot in DiscoverSteamRoots())
            {
                foreach (string libraryRoot in DiscoverSteamLibraryRoots(steamRoot))
                {
                    AddCandidate(
                        candidates,
                        Path.Combine(libraryRoot, "steamapps", "common", "VoiceAttack 2"),
                        "Steam library",
                        40);
                    AddCandidate(
                        candidates,
                        Path.Combine(libraryRoot, "steamapps", "common", "VoiceAttack"),
                        "Steam library",
                        41);
                }
            }
        }

        private static IEnumerable<string> DiscoverSteamRoots()
        {
            List<string> roots = new List<string>();
            AddSteamRootFromRegistry(roots, RegistryHive.CurrentUser, RegistryView.Default, @"Software\Valve\Steam");
            AddSteamRootFromRegistry(roots, RegistryHive.LocalMachine, RegistryView.Registry64, @"SOFTWARE\Valve\Steam");
            AddSteamRootFromRegistry(roots, RegistryHive.LocalMachine, RegistryView.Registry32, @"SOFTWARE\Valve\Steam");
            roots.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Steam"));
            roots.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Steam"));

            return UniqueExistingDirectories(roots);
        }

        private static void AddSteamRootFromRegistry(
            List<string> roots, RegistryHive hive, RegistryView view, string keyPath)
        {
            try
            {
                using (RegistryKey baseKey = RegistryKey.OpenBaseKey(hive, view))
                using (RegistryKey key = baseKey.OpenSubKey(keyPath))
                {
                    if (key == null)
                    {
                        return;
                    }

                    roots.Add(key.GetValue("SteamPath") as string);
                    roots.Add(key.GetValue("InstallPath") as string);
                }
            }
            catch (SecurityException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
            catch (IOException)
            {
            }
        }

        private static IEnumerable<string> DiscoverSteamLibraryRoots(string steamRoot)
        {
            List<string> libraries = new List<string>();
            if (!Directory.Exists(steamRoot))
            {
                return libraries;
            }

            libraries.Add(steamRoot);
            string libraryFolders = Path.Combine(steamRoot, "steamapps", "libraryfolders.vdf");
            if (!File.Exists(libraryFolders))
            {
                return UniqueExistingDirectories(libraries);
            }

            foreach (string line in File.ReadAllLines(libraryFolders))
            {
                Match match = Regex.Match(line, "\"path\"\\s+\"(?<path>.+?)\"");
                if (!match.Success)
                {
                    continue;
                }

                string library = match.Groups["path"].Value.Replace(@"\\", @"\");
                libraries.Add(library);
            }

            return UniqueExistingDirectories(libraries);
        }

        private static string SelectVoiceAttackInstall(List<InstallCandidate> candidates)
        {
            if (candidates.Count == 0)
            {
                Console.WriteLine("No VoiceAttack installation was detected automatically.");
                return PromptForManualPath();
            }

            if (candidates.Count == 1 || !CanPrompt())
            {
                InstallCandidate selected = candidates[0];
                Console.WriteLine("Detected VoiceAttack installation:");
                Console.WriteLine("  " + selected.Path);
                Console.WriteLine("  source: " + selected.Source);
                Console.WriteLine();
                return selected.Path;
            }

            Console.WriteLine("Detected multiple VoiceAttack installations:");
            for (int index = 0; index < candidates.Count; index++)
            {
                Console.WriteLine("  " + (index + 1) + ". " + candidates[index].Path + " (" + candidates[index].Source + ")");
            }

            Console.WriteLine();
            Console.Write("Choose a number, press Enter for 1, or paste a folder path: ");
            string input = Console.ReadLine();
            if (string.IsNullOrWhiteSpace(input))
            {
                return candidates[0].Path;
            }

            int selectedIndex;
            if (int.TryParse(input.Trim(), out selectedIndex)
                && selectedIndex >= 1
                && selectedIndex <= candidates.Count)
            {
                return candidates[selectedIndex - 1].Path;
            }

            string manualPath = NormalizeCandidatePath(input);
            return IsVoiceAttackInstall(manualPath) ? manualPath : null;
        }

        private static string PromptForManualPath()
        {
            if (!CanPrompt())
            {
                return null;
            }

            Console.Write("Paste the VoiceAttack install folder, or press Enter to abort: ");
            string input = Console.ReadLine();
            if (string.IsNullOrWhiteSpace(input))
            {
                return null;
            }

            string manualPath = NormalizeCandidatePath(input);
            return IsVoiceAttackInstall(manualPath) ? manualPath : null;
        }

        private static void WaitForVoiceAttackToClose()
        {
            Process[] running = Process.GetProcessesByName("VoiceAttack");
            if (running.Length == 0)
            {
                return;
            }

            Console.ForegroundColor = ConsoleColor.Yellow;
            Console.WriteLine("VoiceAttack appears to be running.");
            Console.ResetColor();
            Console.WriteLine("Close VoiceAttack before installing or replacing the plugin DLL.");
            if (CanPrompt())
            {
                Console.Write("Press Enter after closing VoiceAttack, or press Enter now to try anyway: ");
                Console.ReadLine();
            }
        }

        private static void AddCandidate(List<InstallCandidate> candidates, string path, string source, int score)
        {
            string normalizedPath = NormalizeCandidatePath(path);
            if (normalizedPath == null)
            {
                return;
            }

            candidates.Add(new InstallCandidate(normalizedPath, source, score));
        }

        private static string NormalizeCandidatePath(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                return null;
            }

            string trimmed = path.Trim().Trim('"');
            if (File.Exists(trimmed))
            {
                return Path.GetDirectoryName(Path.GetFullPath(trimmed));
            }

            if (!Directory.Exists(trimmed))
            {
                return null;
            }

            string fullPath = Path.GetFullPath(trimmed);
            if (string.Equals(Path.GetFileName(fullPath), "Apps", StringComparison.OrdinalIgnoreCase))
            {
                string parent = Directory.GetParent(fullPath)?.FullName;
                if (parent != null)
                {
                    return parent;
                }
            }

            return fullPath;
        }

        private static string DirectoryFromDisplayIcon(string displayIcon)
        {
            if (string.IsNullOrWhiteSpace(displayIcon))
            {
                return null;
            }

            string value = displayIcon.Trim().Trim('"');
            int commaIndex = value.LastIndexOf(',');
            if (commaIndex > 1)
            {
                value = value.Substring(0, commaIndex).Trim().Trim('"');
            }

            return File.Exists(value) ? Path.GetDirectoryName(Path.GetFullPath(value)) : value;
        }

        private static bool LooksLikeVoiceAttackName(string displayName)
        {
            return !string.IsNullOrWhiteSpace(displayName)
                && displayName.IndexOf("VoiceAttack", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static bool IsVoiceAttackInstall(string path)
        {
            if (string.IsNullOrWhiteSpace(path) || !Directory.Exists(path))
            {
                return false;
            }

            return File.Exists(Path.Combine(path, VoiceAttackExeName))
                || File.Exists(Path.Combine(path, VoiceAttackDllName));
        }

        private static string[] UniqueExistingDirectories(IEnumerable<string> paths)
        {
            return paths
                .Where(path => !string.IsNullOrWhiteSpace(path))
                .Select(path => path.Trim().Trim('"'))
                .Where(Directory.Exists)
                .Select(Path.GetFullPath)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray();
        }

        private static string NormalizeKey(string path)
        {
            return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        }

        private static bool CanPrompt()
        {
            return Environment.UserInteractive && !Console.IsInputRedirected;
        }

        private static int Fail(params string[] lines)
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine("Installation failed.");
            Console.ResetColor();
            foreach (string line in lines)
            {
                if (!string.IsNullOrWhiteSpace(line))
                {
                    Console.WriteLine(line);
                }
            }

            PauseIfInteractive();
            return 1;
        }

        private static void PauseIfInteractive()
        {
            if (!CanPrompt())
            {
                return;
            }

            Console.WriteLine();
            Console.Write("Press any key to close...");
            Console.ReadKey(intercept: true);
        }

        private sealed class InstallCandidate
        {
            public InstallCandidate(string path, string source, int score)
            {
                Path = path;
                Source = source;
                Score = score;
            }

            public string Path { get; }

            public string Source { get; }

            public int Score { get; }
        }
    }
}
