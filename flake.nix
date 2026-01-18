{
  description = "Python-based MCP server for mGBA using native Python bindings";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;
        lib = pkgs.lib;

        # Build mGBA from source with Python bindings
        mgba-with-python = pkgs.stdenv.mkDerivation rec {
          pname = "mgba-with-python";
          version = "0.11-dev";

          MACOSX_DEPLOYMENT_TARGET = lib.optionalString pkgs.stdenv.isDarwin "14.0";
          NIX_CFLAGS_COMPILE = lib.optionalString pkgs.stdenv.isDarwin "-mmacosx-version-min=14.0";

          src = pkgs.fetchFromGitHub {
            owner = "mgba-emu";
            repo = "mgba";
            # Pinned commit from 2025-01-17 (0.11-dev)
            rev = "97c4de34889fc990119f7d9a95167f623f17e27d";
            hash = "sha256-KLR1ay5BTn3sL3NDY7HOwKzuPzP+eiADv6lY4YUh0s4=";
          };

          nativeBuildInputs = with pkgs; [
            cmake
            pkg-config
          ] ++ lib.optionals (!pkgs.stdenv.isDarwin) [
            patchelf
          ];

          buildInputs = with pkgs; [
            # Core mGBA dependencies
            libzip
            zlib
            libpng
            sqlite
            libedit

            # FFmpeg for ereader scanning
            ffmpeg

            # Python for bindings
            python
            python.pkgs.cffi
            python.pkgs.cached-property
            python.pkgs.setuptools
            python.pkgs.pip
          ] ++ lib.optionals (!pkgs.stdenv.isDarwin) [
            elfutils
          ];

          cmakeFlags = [
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"
            "-DBUILD_PYTHON=ON"
            "-DBUILD_QT=OFF"
            "-DBUILD_SDL=OFF"
            "-DBUILD_HEADLESS=OFF"
            "-DENABLE_SCRIPTING=OFF"
            "-DUSE_DISCORD_RPC=OFF"
            "-DUSE_FFMPEG=ON"
            "-DUSE_PNG=ON"
            "-DUSE_ZLIB=ON"
            "-DUSE_LIBZIP=ON"
            "-DUSE_SQLITE3=ON"
            "-DENABLE_VFS=ON"
            # CRITICAL: ENABLE_DIRECTORIES is added to ENABLES list when VFS is on,
            # but the cmake variable isn't set, so flags.h doesn't get it.
            # We must set it explicitly so flags.h matches the library's struct layout.
            "-DENABLE_DIRECTORIES=ON"
          ]
          ++ lib.optionals pkgs.stdenv.isDarwin [
            "-DUSE_ELF=OFF"
            "-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0"
            "-DBUILD_GL=OFF"
            "-DBUILD_GLES2=OFF"
            "-DBUILD_GLES3=OFF"
          ]
          ++ lib.optionals (!pkgs.stdenv.isDarwin) [
            "-DUSE_ELF=ON"
          ];

          # Patch the setup.py before building to fix version detection
          postPatch = ''
            substituteInPlace src/platform/python/setup.py \
              --replace-fail "version = '{}.{}.{}'.format(*(get_version_component(p) for p in ('LIB_VERSION_MAJOR', 'LIB_VERSION_MINOR', 'LIB_VERSION_PATCH')))" \
              "version = '${version}'" \
              --replace-fail "if not get_version_component('GIT_TAG'):" \
              "if False:" \
              --replace-fail "'pytest-runner'" \
              "" \
              --replace-fail ", ]" \
              "]"
            
            # Patch gb.py to wrap create_callback calls in try/except
            # These SIO callbacks don't exist in the library and aren't needed for basic emulation
            substituteInPlace src/platform/python/mgba/gb.py \
              --replace-fail 'create_callback("GBSIOPythonDriver", "init")' \
              'try: create_callback("GBSIOPythonDriver", "init")
except: pass' \
              --replace-fail 'create_callback("GBSIOPythonDriver", "deinit")' \
              'try: create_callback("GBSIOPythonDriver", "deinit")
except: pass' \
              --replace-fail 'create_callback("GBSIOPythonDriver", "writeSB")' \
              'try: create_callback("GBSIOPythonDriver", "writeSB")
except: pass' \
              --replace-fail 'create_callback("GBSIOPythonDriver", "writeSC")' \
              'try: create_callback("GBSIOPythonDriver", "writeSC")
except: pass'
            
            # Patch gba.py similarly if it has create_callback calls
            if grep -q "create_callback" src/platform/python/mgba/gba.py 2>/dev/null; then
              substituteInPlace src/platform/python/mgba/gba.py \
                --replace-fail 'create_callback("GBASIOPythonDriver", "init")' \
                'try: create_callback("GBASIOPythonDriver", "init")
except: pass' \
                --replace-fail 'create_callback("GBASIOPythonDriver", "deinit")' \
                'try: create_callback("GBASIOPythonDriver", "deinit")
except: pass' \
                --replace-fail 'create_callback("GBASIOPythonDriver", "load")' \
                'try: create_callback("GBASIOPythonDriver", "load")
except: pass' \
                --replace-fail 'create_callback("GBASIOPythonDriver", "unload")' \
                'try: create_callback("GBASIOPythonDriver", "unload")
except: pass' || true
            fi
          '';

          # Build the mgba-py target which does everything
          buildPhase = ''
            runHook preBuild
            cmake --build . --target mgba-py
            runHook postBuild
          '';

          installPhase = ''
            runHook preInstall
            
            mkdir -p $out/lib
            mkdir -p $out/include/mgba
            mkdir -p $out/${python.sitePackages}

            # Copy the shared library
            if [ -f "libmgba.dylib" ]; then
              cp libmgba.dylib $out/lib/ || true
            fi
            cp libmgba.so* $out/lib/ || true

            if [ -f "$out/lib/libmgba.dylib" ]; then
              ln -sfn libmgba.dylib $out/lib/libmgba.0.11.dylib
            fi

            # Copy headers
            cp -r $src/include/* $out/include/
            
            # Copy generated headers (version.h and flags.h are in build/include/mgba/)
            cp include/mgba/version.h $out/include/mgba/ 2>/dev/null || true
            cp include/mgba/flags.h $out/include/mgba/ 2>/dev/null || true

            # Copy Python package from the build directory
            # The mgba-py target builds to python/lib.*/mgba/
            for mgba_dir in python/lib.*-cp*/mgba; do
              if [ -d "$mgba_dir" ]; then
                cp -r "$mgba_dir" $out/${python.sitePackages}/
              fi
            done

            ${lib.optionalString (!pkgs.stdenv.isDarwin) ''
              # Fix the RPATH on the Python extension to point to our lib directory (Linux)
              for pyfile in $out/${python.sitePackages}/mgba/*.so; do
                patchelf --set-rpath "$out/lib" "$pyfile" 2>/dev/null || true
              done
            ''}

            runHook postInstall
          '';

          # Wrap the library path
          postFixup = lib.optionalString (!pkgs.stdenv.isDarwin) ''
            for pyfile in $out/${python.sitePackages}/mgba/*.so; do
              patchelf --set-rpath "$out/lib:${pkgs.lib.makeLibraryPath buildInputs}" "$pyfile" 2>/dev/null || true
            done
          '';

          meta = with pkgs.lib; {
            description = "mGBA library with Python bindings";
            homepage = "https://mgba.io";
            license = licenses.mpl20;
            platforms = platforms.linux ++ platforms.darwin;
          };
        };

        # Python environment with mgba and dependencies
        pythonEnv = python.withPackages (ps: [
          ps.cffi
          ps.cached-property
          ps.pillow
        ]);

        pymgba-mcp = pkgs.writeShellApplication {
          name = "pymgba-mcp";
          runtimeInputs = [
            pythonEnv
            pkgs.uv
            mgba-with-python
          ];
          text = ''
            ${lib.optionalString pkgs.stdenv.isDarwin ''
              export DYLD_LIBRARY_PATH="${mgba-with-python}/lib"
            ''}
            ${lib.optionalString (!pkgs.stdenv.isDarwin) ''
              export LD_LIBRARY_PATH="${mgba-with-python}/lib"
            ''}
            export PYTHONPATH="${mgba-with-python}/${python.sitePackages}:$PYTHONPATH"
            exec uv run pymgba-mcp "$@"
          '';
        };

      in
      {
        packages = {
          default = pymgba-mcp;
          mgba-with-python = mgba-with-python;
          pymgba-mcp = pymgba-mcp;
        };

        apps = {
          default = flake-utils.lib.mkApp { drv = pymgba-mcp; };
          pymgba-mcp = flake-utils.lib.mkApp { drv = pymgba-mcp; };
        };

        devShells.default = pkgs.mkShell {
          packages = [
            pythonEnv
            pkgs.uv
          ];

          buildInputs = [
            mgba-with-python
          ];

          # Ensure the mgba library and Python module are found
          LD_LIBRARY_PATH = lib.optionalString (!pkgs.stdenv.isDarwin) "${mgba-with-python}/lib";
          DYLD_LIBRARY_PATH = lib.optionalString pkgs.stdenv.isDarwin "${mgba-with-python}/lib";

          shellHook = ''
            echo "pymgba-mcp development shell"
            echo ""
            echo "mGBA library: ${mgba-with-python}/lib"
            echo "mGBA Python: ${mgba-with-python}/${python.sitePackages}"
            echo ""
            export PYTHONPATH="${mgba-with-python}/${python.sitePackages}:$PYTHONPATH"
            echo "PYTHONPATH includes mgba bindings"
            echo ""
            echo "Run: uv run pymgba-mcp"
            echo ""
          '';
        };
      }
    );
}
