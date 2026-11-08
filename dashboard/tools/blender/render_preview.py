"""Offline model QA; camera poses match the web scene. Does not save the scene."""
import bpy, math
from mathutils import Vector
from pathlib import Path
root=Path(bpy.context.scene.get('fridge_dashboard_root','/Users/khang/Desktop/hackathon/dashboard'))
source_scene=bpy.context.scene
scene=bpy.data.scenes.new('Fridge QA Preview')
scene.collection.children.link(bpy.data.collections['FridgeTracker'])
scene.world=bpy.data.worlds.new('QA world')
bpy.context.window.scene=scene
original_door_rotation=bpy.data.objects['DoorPivot'].rotation_euler.copy()
scene.render.engine='CYCLES';scene.cycles.samples=24
scene.render.resolution_x=1440;scene.render.resolution_y=900;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.55,.57,.49,1);scene.world.node_tree.nodes['Background'].inputs[1].default_value=.6
scene.view_settings.view_transform='AgX'
def aim(ob,target): ob.rotation_euler=(Vector(target)-ob.location).to_track_quat('-Z','Y').to_euler()
for name,loc,power,size in [('Softbox left',(-3,-4,4),500,4),('Softbox right',(3,-2,3),350,3),('Ceiling',(0,0,4),180,3),('Interior',(0,-.20,1.6),3,.25)]:
    light=bpy.data.lights.new(name,'AREA');light.energy=power;light.shape='DISK';light.size=size
    ob=bpy.data.objects.new(name,light);scene.collection.objects.link(ob);ob.location=loc;aim(ob,(0,0,.9))
camera=bpy.data.objects.new('QA Camera',bpy.data.cameras.new('QA Camera'));scene.collection.objects.link(camera);scene.camera=camera
camera.data.sensor_fit='VERTICAL';camera.data.clip_start=.008
out=root/'tools/blender/previews';out.mkdir(exist_ok=True)
def render(name,pos,target,fov):
    camera.location=(pos[0],-pos[2],pos[1]);aim(camera,(target[0],-target[2],target[1]));camera.data.lens=camera.data.sensor_height/(2*math.tan(math.radians(fov)/2))
    scene.render.filepath=str(out/(name+'.png'));bpy.ops.render.render(write_still=True)
render('exterior',(2.7,1.95,4.8),(-.95,1.02,0),34)
bpy.data.objects['DoorPivot'].rotation_euler.z=-2.05
for name,height in [('top',1.48),('middle',1.08),('lower',.68)]: render(name,(0,height+.035,.34),(0,height-.035,-.25),78)
bpy.data.objects['DoorPivot'].rotation_euler=original_door_rotation
bpy.context.window.scene=source_scene
print('PREVIEWS_RENDERED',out)
