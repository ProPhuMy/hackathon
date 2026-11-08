"""Run the fridge builder through the actual Blender MCP stdio server."""
import asyncio
import sys
import shutil
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    uvx_path = shutil.which('uvx')
    if not uvx_path:
        raise RuntimeError("uvx not found in PATH. Please install uv and ensure uvx is available.")
    server = StdioServerParameters(command=uvx_path, args=['mcp-for-blender'], env=None)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool('execute_blender_code', {
                'code': "import bpy; print('MCP_VERIFIED', len(bpy.data.collections['FridgeTracker'].objects), 'objects; hinge:', bpy.data.objects.get('DoorPivot') is not None)" if '--verify' in sys.argv else "import bpy\nbpy.context.scene['fridge_dashboard_root'] = " + repr(str(Path(__file__).resolve().parents[2])) + '\n' + Path(__file__).with_name('render_preview.py' if '--render' in sys.argv else 'build_fridge.py').read_text(),
                'user_prompt': "Create a highly detailed fridge and an immersive orbit, door opening, and zoom-inside interaction with an Escape exit.",
            })
            for item in result.content:
                if hasattr(item,'text'): print(item.text)
            if getattr(result, 'is_error', False): raise RuntimeError('Blender MCP model build failed')
asyncio.run(main())
