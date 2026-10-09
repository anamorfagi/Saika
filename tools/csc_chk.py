import glob, os, platform
print(platform.version())
print(glob.glob(r"C:\Windows\Microsoft.NET\Framework64\v4*\csc.exe"))
print("dotnet:", os.system("dotnet --version") == 0)
