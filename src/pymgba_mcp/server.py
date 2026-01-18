"""MCP server for mGBA emulator using native Python bindings."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    ImageContent,
    Tool,
)

from .emulator import get_emulator, EmulatorError

# Create the MCP server
server = Server("pymgba-mcp")


def _error_response(message: str) -> list[TextContent]:
    """Create an error response."""
    return [TextContent(type="text", text=f"Error: {message}")]


def _text_response(data: Any) -> list[TextContent]:
    """Create a text response from data."""
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


def _screenshot_response(
    png_base64: str, text: str | None = None
) -> list[TextContent | ImageContent]:
    """Create a response with a screenshot."""
    result: list[TextContent | ImageContent] = []
    if text:
        result.append(TextContent(type="text", text=text))
    result.append(
        ImageContent(
            type="image",
            data=png_base64,
            mimeType="image/png",
        )
    )
    return result


# Tool definitions
TOOLS = [
    Tool(
        name="load_rom",
        description="Load a Game Boy or GBA ROM file. Must be called before other operations.",
        inputSchema={
            "type": "object",
            "properties": {
                "rom_path": {
                    "type": "string",
                    "description": "Path to the ROM file (.gb, .gbc, .gba)",
                },
                "bios_path": {
                    "type": "string",
                    "description": "Optional path to BIOS file",
                },
            },
            "required": ["rom_path"],
        },
    ),
    Tool(
        name="run_frames",
        description="Run the emulator for N frames and return a screenshot.",
        inputSchema={
            "type": "object",
            "properties": {
                "frames": {
                    "type": "integer",
                    "description": "Number of frames to run (default: 1)",
                    "default": 1,
                },
            },
        },
    ),
    Tool(
        name="press_button",
        description="Press a button for N frames. Buttons: a, b, start, select, up, down, left, right (and l, r for GBA).",
        inputSchema={
            "type": "object",
            "properties": {
                "button": {
                    "type": "string",
                    "description": "Button to press",
                    "enum": ["a", "b", "start", "select", "up", "down", "left", "right", "l", "r"],
                },
                "frames": {
                    "type": "integer",
                    "description": "Frames to hold the button (default: 1)",
                    "default": 1,
                },
            },
            "required": ["button"],
        },
    ),
    Tool(
        name="hold_buttons",
        description="Set buttons to be held continuously until cleared.",
        inputSchema={
            "type": "object",
            "properties": {
                "buttons": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of buttons to hold",
                },
            },
            "required": ["buttons"],
        },
    ),
    Tool(
        name="release_buttons",
        description="Release all held buttons.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="take_screenshot",
        description="Capture the current screen.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="read_memory",
        description="Read bytes from a memory address.",
        inputSchema={
            "type": "object",
            "properties": {
                "address": {
                    "type": "integer",
                    "description": "Memory address (can be hex string like '0xC000')",
                },
                "length": {
                    "type": "integer",
                    "description": "Number of bytes to read (default: 1)",
                    "default": 1,
                },
            },
            "required": ["address"],
        },
    ),
    Tool(
        name="write_memory",
        description="Write bytes to a memory address.",
        inputSchema={
            "type": "object",
            "properties": {
                "address": {
                    "type": "integer",
                    "description": "Memory address",
                },
                "values": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Byte values to write (0-255)",
                },
            },
            "required": ["address", "values"],
        },
    ),
    Tool(
        name="save_state",
        description="Save the current emulator state.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="load_state",
        description="Load a previously saved state.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_registers",
        description="Get CPU register values.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="dump_oam",
        description="Dump sprite (OAM) data.",
        inputSchema={
            "type": "object",
            "properties": {
                "active_only": {
                    "type": "boolean",
                    "description": "Only show sprites on screen (default: true)",
                    "default": True,
                },
            },
        },
    ),
    Tool(
        name="reset",
        description="Reset the emulator to the beginning of the ROM.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_info",
        description="Get current emulator state info (ROM loaded, frame count, etc).",
        inputSchema={"type": "object", "properties": {}},
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent | ImageContent]:
    """Handle tool calls."""
    try:
        emu = get_emulator()

        if name == "load_rom":
            rom_path = arguments["rom_path"]
            bios_path = arguments.get("bios_path")
            info = emu.load_rom(rom_path, bios_path)
            # Run a few frames to initialize and take initial screenshot
            emu.run_frames(10)
            screenshot = emu.take_screenshot_base64()
            return _screenshot_response(
                screenshot,
                f"Loaded ROM: {info['title']} ({info['platform']})\n"
                f"Resolution: {info['width']}x{info['height']}"
            )

        elif name == "run_frames":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            frames = arguments.get("frames", 1)
            frame_count = emu.run_frames(frames)
            screenshot = emu.take_screenshot_base64()
            return _screenshot_response(screenshot, f"Ran {frames} frames. Now at frame {frame_count}.")

        elif name == "press_button":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            button = arguments["button"]
            frames = arguments.get("frames", 1)
            emu.press_button(button, frames)
            screenshot = emu.take_screenshot_base64()
            return _screenshot_response(screenshot, f"Pressed {button} for {frames} frames.")

        elif name == "hold_buttons":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            buttons = arguments["buttons"]
            emu.set_buttons(buttons)
            return _text_response(f"Holding buttons: {', '.join(buttons)}")

        elif name == "release_buttons":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            emu.clear_buttons()
            return _text_response("Released all buttons.")

        elif name == "take_screenshot":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            screenshot = emu.take_screenshot_base64()
            return _screenshot_response(screenshot, f"Screenshot at frame {emu.frame_count}.")

        elif name == "read_memory":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            address = arguments["address"]
            length = arguments.get("length", 1)
            # Handle hex strings
            if isinstance(address, str):
                address = int(address, 16) if address.startswith("0x") else int(address)
            values = emu.read_memory(address, length)
            # Format as hex dump
            hex_str = " ".join(f"{v:02X}" for v in values)
            return _text_response({
                "address": f"0x{address:04X}",
                "length": length,
                "hex": hex_str,
                "values": values,
            })

        elif name == "write_memory":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            address = arguments["address"]
            values = arguments["values"]
            if isinstance(address, str):
                address = int(address, 16) if address.startswith("0x") else int(address)
            emu.write_memory(address, values)
            return _text_response(f"Wrote {len(values)} bytes to 0x{address:04X}")

        elif name == "save_state":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            state = emu.save_state()
            return _text_response(f"Saved state ({len(state)} bytes) at frame {emu.frame_count}")

        elif name == "load_state":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            emu.load_state()
            screenshot = emu.take_screenshot_base64()
            return _screenshot_response(screenshot, f"Loaded state. Now at frame {emu.frame_count}.")

        elif name == "get_registers":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            regs = emu.get_registers()
            # Format registers nicely
            formatted = {k: f"0x{v:04X}" if isinstance(v, int) else v for k, v in regs.items()}
            return _text_response(formatted)

        elif name == "dump_oam":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            active_only = arguments.get("active_only", True)
            sprites = emu.dump_oam()
            if active_only:
                # Filter to sprites that are on screen
                if emu.is_gba:
                    sprites = [s for s in sprites if 0 <= s["x"] < 240 and 0 <= s["y"] < 160]
                else:
                    sprites = [s for s in sprites if -8 < s["x"] < 160 and -16 < s["y"] < 144]
            return _text_response({
                "count": len(sprites),
                "sprites": sprites,
            })

        elif name == "reset":
            if not emu.is_loaded:
                return _error_response("No ROM loaded. Call load_rom first.")
            emu.reset()
            emu.run_frames(1)
            screenshot = emu.take_screenshot_base64()
            return _screenshot_response(screenshot, "Reset emulator.")

        elif name == "get_info":
            info = {
                "loaded": emu.is_loaded,
                "frame_count": emu.frame_count if emu.is_loaded else 0,
                "platform": "GBA" if emu.is_gba else "GB/GBC" if emu.is_loaded else None,
            }
            return _text_response(info)

        else:
            return _error_response(f"Unknown tool: {name}")

    except EmulatorError as e:
        return _error_response(str(e))
    except Exception as e:
        return _error_response(f"Unexpected error: {type(e).__name__}: {e}")


async def run_server() -> None:
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Entry point for the MCP server."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
