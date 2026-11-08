"""Start the installed Blender MCP addon on loopback only."""
import bpy
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / 'Library/Application Support/Blender' / bpy.app.version_string.split()[0].rsplit('.',1)[0] / 'scripts/addons'))
import blender_mcp
blender_mcp.register()
bpy.types.blendermcp_server = blender_mcp.BlenderMCPServer(host='127.0.0.1', port=9876)
bpy.types.blendermcp_server.start()
bpy.context.scene.blendermcp_server_running = True
print('FRIDGE_MCP_READY', flush=True)
