# pymgba-mcp

This is a vibecoded Python-based MCP (Model Context Protocol) server for the mGBA Game Boy/GBA emulator using native Python bindings. It interacts with mGBA through its native Python bindings, allowing not only to take screenshots but also to control the emulator, read and write memory, add breakpoints, and more - meant for vibe coding GB homebrew games.

It also ships as a Nix flake, to build mGBA and the Python bindings all together for a portable, easy to reproduce setup.

(Note: only tested on Linux so far)

## Features

- **Native Python bindings**: Uses mGBA's built-in Python API instead of spawning external processes
- **Full emulator control**: Run frames, step instructions, pause/unpause
- **Memory access**: Read/write memory at any address
- **Button input**: Press and hold Game Boy buttons
- **Screenshots**: Capture the screen at any time
- **Save states**: Save and load emulator state
- **Debugging**: Set breakpoints, read CPU registers, step through code
- **OAM inspection**: View sprite data

## Tools

| Tool | Description |
|------|-------------|
| `run_rom` | Load and run a ROM for N frames, returns screenshot |
| `step_frame` | Run a single frame (or N frames) |
| `press_button` | Press a button (A, B, Start, Select, D-pad) |
| `read_memory` | Read bytes from a memory address |
| `write_memory` | Write bytes to a memory address |
| `read_memory_range` | Read a contiguous range of bytes |
| `take_screenshot` | Capture the current screen |
| `save_state` | Save emulator state |
| `load_state` | Load emulator state |
| `get_registers` | Get CPU register values |
| `dump_oam` | Dump sprite (OAM) data |
| `reset` | Reset the emulator |

## Usage with your favorite vibe coding tool

Install Nix: https://nixos.org/download.html, and add to your MCP settings:

```json
{
  "mcpServers": {
    "pymgba": {
      "command": "nix",
      "args": ["run", "github:zenitraM/pymgba-mcp"],
    }
  }
}
```

## Running with Nix

Install Nix: https://nixos.org/download.html, clone this repo:

```bash
nix run .
```

Or directly from GitHub:

```bash
nix run github:zenitraM/pymgba-mcp
```

