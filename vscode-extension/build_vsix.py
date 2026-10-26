"""Build the .vsix without vsce.

`npx @vscode/vsce package` fails in a restricted sandbox with
`RangeError: WebAssembly.instantiate(): Out of memory` — undici cannot allocate
Wasm memory, so the official packager cannot run.

A .vsix is a ZIP with a fixed structure, so it can be produced directly:

    extension.vsixmanifest      the package metadata
    [Content_Types].xml         the OPC content-type map
    extension/package.json      the extension manifest
    extension/extension.js      the code
    extension/README.md         what the gallery shows

This is not a workaround with different semantics: it is the same format vsce
emits. VS Code installs it from disk the same way.
"""
import json
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent
OUT = SRC / "wengold-0.1.0.vsix"

pkg = json.loads((SRC / "package.json").read_text())

MANIFEST = f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{pkg['name']}" Version="{pkg['version']}" Publisher="{pkg['publisher']}" />
    <DisplayName>{pkg['displayName']}</DisplayName>
    <Description xml:space="preserve">{pkg['description']}</Description>
    <Tags>{','.join(pkg.get('keywords', []))}</Tags>
    <Categories>{','.join(pkg.get('categories', []))}</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{pkg['engines']['vscode']}" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value="" />
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code" />
  </Installation>
  <Dependencies />
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
  </Assets>
</PackageManifest>
"""

CONTENT_TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension=".json" ContentType="application/json" />
  <Default Extension=".js" ContentType="application/javascript" />
  <Default Extension=".md" ContentType="text/markdown" />
  <Default Extension=".vsixmanifest" ContentType="text/xml" />
  <Default Extension=".xml" ContentType="text/xml" />
</Types>
"""


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("extension.vsixmanifest", MANIFEST)
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        for name in ("package.json", "extension.js", "README.md"):
            p = SRC / name
            if p.exists():
                z.write(p, f"extension/{name}")
    # verify what landed
    with zipfile.ZipFile(OUT) as z:
        bad = z.testzip()
        names = z.namelist()
    print(f"  wrote {OUT}  ({OUT.stat().st_size} bytes)")
    print(f"  zip integrity: {'OK' if bad is None else 'CORRUPT at ' + bad}")
    for n in names:
        print(f"    {n}")
    # the manifest must be well-formed and match package.json
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(OUT) as z:
        root = ET.fromstring(z.read("extension.vsixmanifest"))
        ct = ET.fromstring(z.read("[Content_Types].xml"))
    ns = {"v": "http://schemas.microsoft.com/developer/vsx-schema/2011"}
    ident = root.find(".//v:Identity", ns)
    print(f"  manifest identity: {ident.get('Id')} {ident.get('Version')} "
          f"by {ident.get('Publisher')}")
    assert ident.get("Id") == pkg["name"] and ident.get("Version") == pkg["version"]
    assert ct.tag.endswith("Types")
    print("  manifest and content-types parse, identity matches package.json")


main()
