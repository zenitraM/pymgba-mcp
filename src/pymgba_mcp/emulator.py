"""Emulator wrapper using mGBA's native Python bindings (low-level cffi API).

This module provides a clean interface to mGBA's emulation capabilities using
the low-level cffi bindings directly, which avoids issues with the high-level
Python wrappers.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from mgba._pylib import ffi, lib


class EmulatorError(Exception):
    """Exception raised for emulator errors."""


class Emulator:
    """Wrapper around mGBA's Python bindings for Game Boy/GBA emulation.
    
    Uses the low-level cffi API for maximum stability.
    """

    # Button mappings (these are the same for GB and GBA)
    BUTTONS = {
        "a": 0,       # GBA_KEY_A
        "b": 1,       # GBA_KEY_B
        "select": 2,  # GBA_KEY_SELECT
        "start": 3,   # GBA_KEY_START
        "right": 4,   # GBA_KEY_RIGHT
        "left": 5,    # GBA_KEY_LEFT
        "up": 6,      # GBA_KEY_UP
        "down": 7,    # GBA_KEY_DOWN
        "r": 8,       # GBA_KEY_R (GBA only)
        "l": 9,       # GBA_KEY_L (GBA only)
    }

    def __init__(self) -> None:
        """Initialize the emulator wrapper."""
        self._core = None
        self._video_buffer = None
        self._video_width = 0
        self._video_height = 0
        self._screen_width = 0
        self._screen_height = 0
        self._screen_offset_x = 0
        self._screen_offset_y = 0
        self._rom_path: str | None = None
        self._is_gba: bool = False
        self._savestate: bytes | None = None
        self._held_keys: int = 0

    @property
    def is_loaded(self) -> bool:
        """Check if a ROM is loaded."""
        return self._core is not None

    @property
    def is_gba(self) -> bool:
        """Check if the loaded ROM is a GBA ROM."""
        return self._is_gba

    @property
    def buttons(self) -> dict[str, int]:
        """Get the button mapping for the current platform."""
        if self._is_gba:
            return self.BUTTONS
        else:
            # GB doesn't have L/R
            return {k: v for k, v in self.BUTTONS.items() if k not in ("l", "r")}

    @property
    def frame_count(self) -> int:
        """Get the current frame count."""
        if not self._core:
            return 0
        return self._core.frameCounter(self._core)

    def load_rom(self, rom_path: str, bios_path: str | None = None) -> dict[str, Any]:
        """Load a ROM file.
        
        Args:
            rom_path: Path to the ROM file (.gb, .gbc, .gba)
            bios_path: Optional path to BIOS file
            
        Returns:
            Dict with ROM info (title, platform, dimensions)
        """
        path = Path(rom_path)
        if not path.exists():
            raise EmulatorError(f"ROM file not found: {rom_path}")

        # Detect platform from extension
        ext = path.suffix.lower()
        self._is_gba = ext == ".gba"
        platform = lib.mPLATFORM_GBA if self._is_gba else lib.mPLATFORM_GB

        # Create and initialize core
        self._core = lib.mCoreCreate(platform)
        if self._core == ffi.NULL:
            raise EmulatorError(f"Failed to create core for platform: {platform}")

        if not self._core.init(self._core):
            self._core = None
            raise EmulatorError("Failed to initialize core")

        # Initialize config
        lib.mCoreInitConfig(self._core, ffi.NULL)

        # Load the ROM
        if not lib.mCoreLoadFile(self._core, rom_path.encode()):
            self._core.deinit(self._core)
            self._core = None
            raise EmulatorError(f"Failed to load ROM: {rom_path}")

        self._rom_path = rom_path

        # Load BIOS if provided
        if bios_path:
            bios_vf = lib.VFileOpen(bios_path.encode(), ord('r'))
            if bios_vf != ffi.NULL:
                self._core.loadBIOS(self._core, bios_vf, 0)

        # Set up video buffer using the base size (before reset) to ensure
        # the renderer writes into our buffer.
        width = ffi.new('unsigned*')
        height = ffi.new('unsigned*')
        self._core.baseVideoSize(self._core, width, height)
        self._video_width = width[0]
        self._video_height = height[0]
        self._video_buffer = ffi.new(f'uint32_t[{self._video_width * self._video_height}]')
        self._core.setVideoBuffer(self._core, self._video_buffer, self._video_width)

        # Reset to start fresh
        self._core.reset(self._core)

        # Cache the current visible area (used to crop screenshots)
        screen_width = ffi.new('unsigned*')
        screen_height = ffi.new('unsigned*')
        self._core.currentVideoSize(self._core, screen_width, screen_height)
        self._screen_width = screen_width[0]
        self._screen_height = screen_height[0]
        self._screen_offset_x = 0
        self._screen_offset_y = 0

        # Get game info
        game_info = ffi.new('struct mGameInfo*')
        self._core.getGameInfo(self._core, game_info)
        title = ffi.string(game_info.title).decode('ascii', errors='replace').strip()

        return {
            "title": title or "Unknown",
            "platform": "GBA" if self._is_gba else "GB/GBC",
            "width": self._screen_width or self._video_width,
            "height": self._screen_height or self._video_height,
            "rom_path": rom_path,
        }

    def reset(self) -> None:
        """Reset the emulator."""
        if not self._core:
            raise EmulatorError("No ROM loaded")
        self._core.reset(self._core)
        self._held_keys = 0

    def run_frames(self, count: int = 1) -> int:
        """Run the emulator for a number of frames.
        
        Args:
            count: Number of frames to run
            
        Returns:
            Current frame count after running
        """
        if not self._core:
            raise EmulatorError("No ROM loaded")

        for _ in range(count):
            self._core.runFrame(self._core)

        return self._core.frameCounter(self._core)

    def step(self) -> None:
        """Execute a single CPU instruction."""
        if not self._core:
            raise EmulatorError("No ROM loaded")
        self._core.step(self._core)

    def _button_to_key(self, button: str) -> int:
        """Convert button name to key bitmask."""
        button_lower = button.lower()
        if button_lower not in self.buttons:
            valid = ", ".join(self.buttons.keys())
            raise EmulatorError(f"Invalid button: {button}. Valid buttons: {valid}")
        return 1 << self.buttons[button_lower]

    def press_button(self, button: str, frames: int = 1) -> None:
        """Press a button for a number of frames.
        
        Args:
            button: Button name (a, b, start, select, up, down, left, right, l, r)
            frames: Number of frames to hold the button
        """
        if not self._core:
            raise EmulatorError("No ROM loaded")

        key = self._button_to_key(button)

        # Press the button
        self._core.addKeys(self._core, key)

        # Hold for specified frames
        for _ in range(frames):
            self._core.runFrame(self._core)

        # Release the button
        self._core.clearKeys(self._core, key)

    def hold_buttons(self, buttons: list[str]) -> None:
        """Start holding the specified buttons.
        
        Args:
            buttons: List of button names to hold
        """
        if not self._core:
            raise EmulatorError("No ROM loaded")

        keys = 0
        for button in buttons:
            keys |= self._button_to_key(button)

        self._held_keys |= keys
        self._core.setKeys(self._core, self._held_keys)

    def release_buttons(self, buttons: list[str] | None = None) -> None:
        """Release the specified buttons, or all if none specified.
        
        Args:
            buttons: List of button names to release, or None for all
        """
        if not self._core:
            raise EmulatorError("No ROM loaded")

        if buttons is None:
            self._held_keys = 0
        else:
            for button in buttons:
                key = self._button_to_key(button)
                self._held_keys &= ~key

        self._core.setKeys(self._core, self._held_keys)

    def set_buttons(self, buttons: list[str]) -> None:
        """Set exactly which buttons are held (replaces current state).
        
        Args:
            buttons: List of button names to hold
        """
        if not self._core:
            raise EmulatorError("No ROM loaded")

        keys = 0
        for button in buttons:
            keys |= self._button_to_key(button)

        self._held_keys = keys
        self._core.setKeys(self._core, self._held_keys)

    def clear_buttons(self) -> None:
        """Release all buttons."""
        if not self._core:
            raise EmulatorError("No ROM loaded")
        self._held_keys = 0
        self._core.setKeys(self._core, 0)

    def take_screenshot(self) -> bytes:
        """Take a screenshot and return as PNG bytes.
        
        Returns:
            PNG image data as bytes
        """
        if not self._core or not self._video_buffer:
            raise EmulatorError("No ROM loaded")

        # Import PIL for image handling
        try:
            from PIL import Image
        except ImportError:
            raise EmulatorError("Pillow is required for screenshots")

        # Convert the video buffer to bytes
        # mGBA uses a 32-bit pixel format; interpret as BGRA by default.
        width = self._video_width
        height = self._video_height

        if width <= 0 or height <= 0:
            raise EmulatorError("Video buffer not initialized")

        raw_data = bytes(ffi.buffer(self._video_buffer, width * height * 4))

        # mGBA's native format is mCOLOR_XBGR8; in little endian that is
        # byte order R, G, B, X (or A if alpha is present).
        alpha_bytes = raw_data[3::4]
        if alpha_bytes and all(alpha == 0 for alpha in alpha_bytes):
            img = Image.frombytes("RGB", (width, height), raw_data, "raw", "RGBX")
        else:
            img = Image.frombytes("RGBA", (width, height), raw_data, "raw", "RGBA")

        if self._screen_width and self._screen_height:
            right = self._screen_offset_x + self._screen_width
            bottom = self._screen_offset_y + self._screen_height
            img = img.crop((self._screen_offset_x, self._screen_offset_y, right, bottom))
        
        # Save to PNG in memory
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def take_screenshot_base64(self) -> str:
        """Take a screenshot and return as base64-encoded PNG.
        
        Returns:
            Base64-encoded PNG string
        """
        png_bytes = self.take_screenshot()
        return base64.b64encode(png_bytes).decode("ascii")

    def read_memory(self, address: int, length: int = 1) -> list[int]:
        """Read bytes from memory.
        
        Args:
            address: Memory address to read from
            length: Number of bytes to read
            
        Returns:
            List of byte values
        """
        if not self._core:
            raise EmulatorError("No ROM loaded")

        result = []
        for i in range(length):
            try:
                value = self._core.busRead8(self._core, address + i)
                result.append(value & 0xFF)
            except Exception:
                result.append(0)

        return result

    def write_memory(self, address: int, values: list[int]) -> None:
        """Write bytes to memory.
        
        Args:
            address: Memory address to write to
            values: List of byte values to write
        """
        if not self._core:
            raise EmulatorError("No ROM loaded")

        for i, value in enumerate(values):
            try:
                self._core.busWrite8(self._core, address + i, value & 0xFF)
            except Exception as e:
                raise EmulatorError(f"Failed to write to address {hex(address + i)}: {e}")

    def read_u8(self, address: int) -> int:
        """Read a single byte from memory."""
        return self.read_memory(address, 1)[0]

    def read_u16(self, address: int) -> int:
        """Read a 16-bit value from memory (little-endian)."""
        if not self._core:
            raise EmulatorError("No ROM loaded")
        return self._core.busRead16(self._core, address) & 0xFFFF

    def read_u32(self, address: int) -> int:
        """Read a 32-bit value from memory (little-endian)."""
        if not self._core:
            raise EmulatorError("No ROM loaded")
        return self._core.busRead32(self._core, address) & 0xFFFFFFFF

    def save_state(self) -> bytes:
        """Save the current emulator state.
        
        Returns:
            Savestate data as bytes
        """
        if not self._core:
            raise EmulatorError("No ROM loaded")

        # Get state size
        state_size = self._core.stateSize(self._core)
        state_buf = ffi.new(f'unsigned char[{state_size}]')
        
        if not self._core.saveState(self._core, state_buf):
            raise EmulatorError("Failed to save state")

        state = bytes(ffi.buffer(state_buf, state_size))
        self._savestate = state
        return state

    def load_state(self, state: bytes | None = None) -> None:
        """Load a saved emulator state.
        
        Args:
            state: Savestate data, or None to use the last saved state
        """
        if not self._core:
            raise EmulatorError("No ROM loaded")

        if state is None:
            state = self._savestate

        if state is None:
            raise EmulatorError("No savestate available")

        # Check state size
        expected_size = self._core.stateSize(self._core)
        if len(state) < expected_size:
            raise EmulatorError(f"State data too small: {len(state)} < {expected_size}")

        if not self._core.loadState(self._core, state):
            raise EmulatorError("Failed to load state")

    def get_registers(self) -> dict[str, int]:
        """Get CPU register values.
        
        Returns:
            Dict mapping register names to values
        """
        if not self._core:
            raise EmulatorError("No ROM loaded")

        # Get the CPU pointer and cast appropriately
        cpu = self._core.cpu

        if self._is_gba:
            # ARM CPU - cast to ARMCore
            arm = ffi.cast("struct ARMCore*", cpu)
            return {
                "r0": arm.gprs[0],
                "r1": arm.gprs[1],
                "r2": arm.gprs[2],
                "r3": arm.gprs[3],
                "r4": arm.gprs[4],
                "r5": arm.gprs[5],
                "r6": arm.gprs[6],
                "r7": arm.gprs[7],
                "r8": arm.gprs[8],
                "r9": arm.gprs[9],
                "r10": arm.gprs[10],
                "r11": arm.gprs[11],
                "r12": arm.gprs[12],
                "sp": arm.gprs[13],
                "lr": arm.gprs[14],
                "pc": arm.gprs[15],
                "cpsr": arm.cpsr.packed,
            }
        else:
            # SM83 (Game Boy) CPU - cast to SM83Core
            sm83 = ffi.cast("struct SM83Core*", cpu)
            return {
                "a": sm83.a,
                "f": sm83.f.packed,
                "b": sm83.b,
                "c": sm83.c,
                "d": sm83.d,
                "e": sm83.e,
                "h": sm83.h,
                "l": sm83.l,
                "sp": sm83.sp,
                "pc": sm83.pc,
            }

    def dump_oam(self) -> list[dict[str, int]]:
        """Dump Object Attribute Memory (sprite data).
        
        Returns:
            List of sprite entries with position, tile, and attributes
        """
        if not self._core:
            raise EmulatorError("No ROM loaded")

        sprites = []

        if self._is_gba:
            # GBA has 128 sprites, each 8 bytes at 0x07000000
            oam_base = 0x07000000
            for i in range(128):
                addr = oam_base + i * 8
                attr0 = self.read_u16(addr)
                attr1 = self.read_u16(addr + 2)
                attr2 = self.read_u16(addr + 4)

                y = attr0 & 0xFF
                x = attr1 & 0x1FF
                tile = attr2 & 0x3FF
                palette = (attr2 >> 12) & 0xF

                sprites.append({
                    "index": i,
                    "x": x,
                    "y": y,
                    "tile": tile,
                    "palette": palette,
                    "attr0": attr0,
                    "attr1": attr1,
                    "attr2": attr2,
                })
        else:
            # Game Boy has 40 sprites, each 4 bytes at 0xFE00
            oam_base = 0xFE00
            for i in range(40):
                addr = oam_base + i * 4
                mem = self.read_memory(addr, 4)
                y = mem[0]
                x = mem[1]
                tile = mem[2]
                flags = mem[3]

                sprites.append({
                    "index": i,
                    "y": y - 16,  # Adjust for GB sprite offset
                    "x": x - 8,   # Adjust for GB sprite offset
                    "tile": tile,
                    "flags": flags,
                    "priority": (flags >> 7) & 1,
                    "y_flip": (flags >> 6) & 1,
                    "x_flip": (flags >> 5) & 1,
                    "palette": (flags >> 4) & 1,  # DMG palette (0=OBP0, 1=OBP1)
                    "bank": (flags >> 3) & 1,     # CGB tile bank
                    "cgb_palette": flags & 0x7,   # CGB palette
                })

        return sprites

    def get_info(self) -> dict[str, Any]:
        """Get emulator state information.
        
        Returns:
            Dict with current emulator state
        """
        if not self._core:
            return {
                "loaded": False,
            }

        return {
            "loaded": True,
            "rom_path": self._rom_path,
            "platform": "GBA" if self._is_gba else "GB/GBC",
            "frame_count": self.frame_count,
            "width": self._video_width,
            "height": self._video_height,
        }

    def close(self) -> None:
        """Close the emulator and release resources."""
        if self._core:
            self._core.deinit(self._core)
        self._core = None
        self._video_buffer = None
        self._rom_path = None
        self._savestate = None
        self._held_keys = 0


# Global emulator instance for MCP session
_emulator: Emulator | None = None


def get_emulator() -> Emulator:
    """Get or create the global emulator instance."""
    global _emulator
    if _emulator is None:
        _emulator = Emulator()
    return _emulator
