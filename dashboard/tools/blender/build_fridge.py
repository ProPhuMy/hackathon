"""Detailed appliance and six selectable food groups, authored through Blender MCP.
Meters; front -Y. Export converts Z-up to Three.js Y-up.
"""
import bpy
import math
import random
from pathlib import Path
root = Path(bpy.context.scene.get('fridge_dashboard_root', '/Users/khang/Desktop/hackathon/dashboard'))
collection = bpy.data.collections.get('FridgeTracker')
if collection:
    for ob in list(collection.objects): bpy.data.objects.remove(ob, do_unlink=True)
else:
    collection = bpy.data.collections.new('FridgeTracker')
    bpy.context.scene.collection.children.link(collection)
objects = []
def own(ob, name, parent=None):
    for c in list(ob.users_collection): c.objects.unlink(ob)
    collection.objects.link(ob); ob.name = name
    if parent: ob.parent = parent
    objects.append(ob)
    return ob

def mat(name, color, metal=0, rough=.4, alpha=1, emission=0):
    m = bpy.data.materials.new(name); m.diffuse_color = (*color, alpha); m.use_nodes = True
    p = m.node_tree.nodes.get('Principled BSDF')
    for key, val in [('Base Color', (*color, alpha)), ('Metallic', metal), ('Roughness', rough), ('Alpha', alpha)]: p.inputs[key].default_value = val
    if alpha < 1: m.surface_render_method = 'DITHERED'
    if emission:
        p.inputs['Emission Color'].default_value = (*color,1); p.inputs['Emission Strength'].default_value = emission
    return m
steel = mat('Satin aluminum', (.56,.59,.57), .88,.3)
chrome = mat('Polished edge metal', (.69,.73,.71), .95,.18)
graphite = mat('Graphite rubber', (.026,.034,.03), .05,.53)
ivory = mat('Porcelain liner', (.81,.85,.79), .08,.27)
white = mat('Warm white polymer', (.94,.93,.85), .0,.35)
glass = mat('Green glass shelf', (.39,.62,.51), .2,.22, .34)
clear = mat('Clear food container', (.70,.81,.72), .0,.22,.28)
ink = mat('Printed charcoal', (.045,.068,.049), .0,.65)
paper = mat('Cream paper labels', (.88,.84,.67), .0,.85)
green = mat('Oat carton sage', (.39,.53,.32), .0,.65)
orange = mat('Juice tangerine', (.9,.32,.055), .0,.45)
terra = mat('Lunchbox terracotta', (.53,.22,.11), .0,.38)
coffee = mat('Amber brown glass', (.16,.057,.018), .12,.19)
red = mat('Apple red', (.53,.055,.025), .0,.23)
leaf = mat('Leaf green', (.2,.31,.035), .0,.48)
led = mat('Warm LED diffuser', (.86,1,.78), .0,.2, emission=4)

def finish(ob, material, bevel=0):
    ob.data.materials.append(material)
    if bevel:
        mod=ob.modifiers.new('Machined radii','BEVEL'); mod.width=bevel; mod.segments=5
        ob.modifiers.new('Surface normals','WEIGHTED_NORMAL')
    return ob

def cube(name, loc, size, material, bevel=.008, parent=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    ob=own(bpy.context.object,name,parent); ob.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    return finish(ob,material,bevel)

def cylinder(name, loc, radius, depth, material, parent=None, r2=None):
    bpy.ops.mesh.primitive_cone_add(vertices=48, radius1=radius, radius2=radius if r2 is None else r2, depth=depth, location=loc)
    ob=own(bpy.context.object,name,parent)
    for face in ob.data.polygons: face.use_smooth=True
    return finish(ob,material,.002)

def sphere(name,loc,scale,material,parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, location=loc)
    ob=own(bpy.context.object,name,parent); ob.scale=scale
    for face in ob.data.polygons: face.use_smooth=True
    return finish(ob,material)

def text(name, body, loc, size, material=ink, parent=None, align='CENTER'):
    curve=bpy.data.curves.new(name,'FONT'); curve.body=body; curve.size=size; curve.extrude=.00008; curve.align_x=align; curve.space_line=1.15
    ob=own(bpy.data.objects.new(name,curve),name,parent); ob.location=loc; ob.rotation_euler=(math.pi/2,0,0); ob.data.materials.append(material)
    return ob

def group(name,loc):
    ob=own(bpy.data.objects.new(name,None),name); ob.location=loc
    return ob

# Separate panels, a rolled perimeter lip, recessed toe kick and adjustable feet.
cube('Back panel',(0,.39,.95),(1.08,.08,1.8),steel,.03)
for x in [-.52,.52]: cube('Side shell',(x,0,.95),(.08,.81,1.8),steel,.025)
for z in [.085,1.815]: cube('Shell cap',(0,0,z),(1.08,.81,.07),steel,.025)
for x in [-.43,.43]:
    for y in [-.29,.28]: cylinder('Adjustable foot',(x,y,.035),.045,.07,graphite)
cube('Toe kick',(0,-.377,.10),(.94,.038,.07),graphite)
for x in [i*.038 for i in range(-10,11)]: cube('Vent slot',(x,-.401,.10),(.021,.005,.023),ink,.004)
# The insulated liner has real depth and ribbed shelf tracks.
cube('Liner back',(0,.337,.95),(.95,.035,1.64),ivory,.025)
for x in [-.468,.468]:
    cube('Liner side',(x,0,.95),(.035,.71,1.64),ivory,.015)
    for z in [.51,.92,1.33]: cube('Molded shelf track',(x*.965,0,z),(.025,.65,.023),white,.009)
for z in [.15,1.74]: cube('Liner cap',(0,0,z),(.94,.71,.035),ivory,.018)
for x in [-.486,.486]: cube('Front lip',(x,-.377,.95),(.022,.035,1.65),chrome,.009)
for z in [.13,1.77]: cube('Front lip',(0,-.377,z),(.985,.035,.022),chrome,.009)
# Multi-ridge compression gasket, four sides with small corner radii.
for offset in [0,.009,.018]:
    for x in [-.504+offset,.504-offset]: cube('Seal ridge',(x,-.403,.95),(.006,.013,1.69-2*offset),graphite,.002)
    for z in [.106+offset,1.794-offset]: cube('Seal ridge',(0,-.403,z),(1.01-2*offset,.013,.006),graphite,.002)
for i,z in enumerate([.51,.92,1.33]):
    cube('Tempered shelf',(0,-.005,z),(.9,.65,.012),glass,.004)
    cube('Shelf polished edge',(0,-.335,z),(.91,.018,.021),chrome,.004)
    cube('Shelf label plate',(-.34,-.346,z),(.17,.004,.034),paper,.002)
    text('Shelf numbering',f'0{3-i} / FRESH',(-.34,-.35,z-.006),.014)
# Crisper bin with a recessed grip and a transparent front.
cube('Crisper bottom',(0,.035,.21),(.85,.55,.023),white,.013)
cube('Crisper front',(0,-.25,.34),(.85,.025,.25),clear,.014)
cube('Crisper handle',(0,-.278,.437),(.31,.035,.025),white,.008)
for x in [-.417,.417]: cube('Crisper sides',(x,.02,.33),(.02,.55,.23),clear,.01)
text('Crisper print','FRESH ZONE',(0,-.268,.29),.025,ink)
# Upper freezer flap, ventilation, thermostat, screw heads and dual LED strips.
cube('Freezer compartment',(0,.25,1.645),(.81,.16,.15),white,.021)
cube('Freezer inset',(0,.163,1.64),(.74,.014,.105),ivory,.011)
cube('Freezer pull',(.24,.142,1.64),(.16,.025,.025),chrome,.006)
text('Freezer stars','*  *  *',(-.2,.152,1.63),.027)
for i in range(10): cube('Rear cooling vent',(-.225+i*.05,.313,1.22),(.029,.007,.065),graphite,.007)
text('Liner insignia','F R I D G E  /  0 0 1',(0,.313,1.1),.024,ink)
for x in [-.434,.434]: cube('Vertical LED strip',(x,-.12,.99),(.009,.025,1.28),led,.004)
for x in [-.36,.36]:
    for z in [.27,1.48]:
        screw=cylinder('Recessed fastener',(x,.31,z),.008,.005,chrome); screw.rotation_euler.x=math.pi/2
        cube('Screw slot',(x,.305,z),(.009,.002,.0015),graphite,.0005)
thermostat=cylinder('Thermostat dial',(.35,.29,1.5),.04,.025,white); thermostat.rotation_euler.x=math.pi/2
text('Dial setting','4',(.35,.27,1.49),.024)
# Full independent left-hinged door, folded skin and recessed top handle.
hinge=group('DoorPivot',(-.54,-.43,0))
cube('Door front',(.54,-.064,.95),(1.08,.105,1.8),steel,.035,hinge)
cube('Door interior liner',(.54,.005,.95),(.98,.036,1.69),ivory,.028,hinge)
cube('Top recessed grip',(.54,-.111,1.824),(.93,.04,.045),graphite,.014,hinge)
cube('Handle rolled lip',(.54,-.133,1.835),(.96,.018,.014),chrome,.006,hinge)
cube('Lower door trim',(.54,-.072,.065),(1.02,.09,.024),graphite,.01,hinge)
for z in [.18,1.72]:
    cylinder('Door hinge barrel',(.015,.025,z),.018,.09,chrome,hinge)
for z in [.42,1.04]:
    cube('Door rack floor',(.54,.095,z),(.81,.19,.02),white,.012,hinge)
    cube('Door rack guard',(.54,.175,z+.065),(.81,.025,.13),clear,.012,hinge)
    cube('Door rack rail',(.54,.183,z+.13),(.81,.02,.015),chrome,.006,hinge)
    for x in [.14,.94]: cube('Rack end cap',(x,.09,z+.065),(.02,.19,.13),white,.009,hinge)
text('Brand badge','fridge',(.54,-.12,1.63),.047,graphite,hinge)
text('Model badge','001 / SHARED SPACE',(.54,-.12,.22),.014,graphite,hinge)
note=cube('Lunch note',(.31,-.123,1.22),(.29,.003,.27),paper,.001,hinge)
text('Note headline','HANDS OFF\nMY LUNCH.',(.31,-.127,1.26),.032,ink,hinge)
text('Note signature','— KHANG',(.31,-.127,1.145),.016,ink,hinge)
magnet=cylinder('Magnetic pin',(.31,-.134,1.35),.016,.008,terra,hinge); magnet.rotation_euler.x=math.pi/2
# Each food is a parent group; all details share its itemIndex for picking.
foods=[group('Food_'+str(i),loc) for i,loc in enumerate([(-.225,-.02,1.34),(.205,-.025,1.34),(-.23,-.03,.93),(.22,-.025,.93),(-.22,-.035,.52),(.22,-.015,.52)])]
for i,f in enumerate(foods): f['itemIndex']=i
# Oat carton: folded gable, seam, screw cap, print and paper emboss.
f=foods[0]
cube('Oat carton',(0,0,.125),(.155,.145,.25),green,.007,f)
verts=[(-.077,-.072,.25),(.077,-.072,.25),(.077,.072,.25),(-.077,.072,.25),(-.077,0,.303),(.077,0,.303)]
mesh=bpy.data.meshes.new('Folded carton'); mesh.from_pydata(verts,[],[(0,1,5,4),(3,4,5,2),(0,4,3),(1,2,5),(0,3,2,1)]); mesh.update()
ob=own(bpy.data.objects.new('Gable fold',mesh),'Gable fold',f); finish(ob,green)
cube('Carton top seam',(0,0,.305),(.156,.009,.012),paper,.002,f)
cube('Carton label',(0,-.074,.13),(.127,.002,.18),paper,.001,f)
text('Oat title','OAT',(0,-.077,.18),.041,ink,f)
text('Oat subtitle','BARISTA\n\n1L / VIET',(0,-.077,.12),.013,ink,f)
cap=cylinder('Oat cap',(.035,-.042,.28),.017,.012,white,f); cap.rotation_euler.x=math.pi/4
for i in range(4): cube('Carton baseline',(0,-.077,.06+i*.006),(.09,.001,.0018),green,.0005,f)
# Lunch box with a raised lid, silicone seal and clips; pasta visible through lid.
f=foods[1]
cube('Lunch container',(0,0,.055),(.29,.195,.11),terra,.022,f)
cube('Silicone lid seal',(0,0,.112),(.301,.205,.012),graphite,.012,f)
cube('Translucent lid',(0,0,.124),(.31,.213,.016),clear,.015,f)
for x in [-.151,.151]: cube('Lock clip',(x,-.005,.105),(.018,.064,.035),white,.006,f)
cube('Lunch ownership label',(0,-.099,.061),(.17,.002,.055),paper,.004,f)
text('Lunch owner','KHANG',(0,-.102,.052),.025,ink,f)
for i in range(7):
    noodle=cylinder('Pasta',(-.1+i*.032,0,.109),.009,.065,paper,f); noodle.rotation_euler.x=1.3
# Yogurt: tapered cup, crimped foil rim, pull tab and printed panel.
f=foods[2]
cylinder('Yogurt cup',(0,0,.065),.057,.13,white,f,r2=.077)
cylinder('Yogurt foil lid',(0,0,.135),.08,.008,chrome,f)
cube('Foil pull tab',(.075,-.022,.138),(.035,.026,.003),chrome,.008,f)
cube('Yogurt label',(0,-.071,.075),(.099,.006,.061),green,.006,f)
text('Yogurt title','GREEK',(0,-.076,.081),.021,white,f)
text('Yogurt owner','PHONG',(0,-.076,.059),.011,white,f)
for i in range(24):
    a=2*math.pi*i/24; cylinder('Lid crimp',(.077*math.cos(a),.077*math.sin(a),.136),.0017,.008,white,f)
# Cold brew bottle: curved shoulders, neck ring, knurled screw cap and wrap label.
f=foods[3]
cylinder('Coffee bottle',(0,0,.10),.061,.20,coffee,f)
sphere('Bottle shoulder',(0,0,.19),(.061,.061,.048),coffee,f)
cylinder('Bottle neck',(0,0,.236),.029,.054,coffee,f)
cylinder('Bottle cap',(0,0,.266),.033,.035,graphite,f)
for i in range(24):
    a=2*math.pi*i/24; cylinder('Cap grip',(.033*math.cos(a),.033*math.sin(a),.266),.0013,.029,graphite,f)
cube('Coffee label',(0,-.061,.112),(.095,.004,.098),paper,.004,f)
text('Cold brew type','COLD\nBREW',(0,-.065,.132),.025,ink,f)
text('Cold brew owner','DANG / 250ML',(0,-.065,.078),.009,ink,f)
# Apples in a molded pulp tray: curved bodies, dimples, stems and leaves.
f=foods[4]
cube('Produce tray',(0,0,.018),(.275,.18,.035),paper,.018,f)
for x,y,scale in [(-.064,-.015,1),(.062,.014,.92)]:
    sphere('Apple',(x,y,.081),(.065*scale,.061*scale,.066*scale),red,f)
    sphere('Apple crown',(x,y,.132),(.026,.022,.012),red,f)
    stem=cylinder('Apple stem',(x,y,.153),.004,.027,coffee,f); stem.rotation_euler.y=.25
    l=sphere('Apple leaf',(x+.022,y,.154),(.027,.011,.003),leaf,f); l.rotation_euler.y=-.35
cube('Produce label',(0,-.093,.025),(.16,.003,.035),green,.003,f)
text('Produce owner','KHANG / APPLES',(0,-.096,.019),.012,white,f)
# Juice bottle has a ribbed body, orange liquid color, a collar and printed label.
f=foods[5]
cylinder('Juice bottle',(0,0,.115),.067,.23,orange,f)
sphere('Juice shoulders',(0,0,.224),(.066,.066,.045),orange,f)
cylinder('Juice neck',(0,0,.258),.032,.04,orange,f)
cylinder('Juice cap',(0,0,.285),.037,.03,green,f)
for z in [.029,.043,.058,.2,.216]: cylinder('Bottle molded rib',(0,0,z),.069,.004,orange,f)
cube('Juice label',(0,-.068,.13),(.107,.003,.111),paper,.006,f)
text('Juice type','100%\nORANGE',(0,-.072,.155),.021,ink,f)
text('Juice owner','VIET / 500ML',(0,-.072,.095),.01,ink,f)
# Merge static details by material and parent: detailed geometry without hundreds
# of draw calls. Keep DoorPivot and Food_i nodes as independent animation/pick roots.
for ob in list(objects):
    if ob.type == 'FONT':
        bpy.ops.object.select_all(action='DESELECT'); ob.select_set(True); bpy.context.view_layer.objects.active=ob
        bpy.ops.object.convert(target='MESH')
for ob in list(collection.objects):
    if ob.type == 'MESH':
        bpy.ops.object.select_all(action='DESELECT'); ob.select_set(True); bpy.context.view_layer.objects.active=ob
        for modifier in list(ob.modifiers): bpy.ops.object.modifier_apply(modifier=modifier.name)
buckets={}
for ob in list(collection.objects):
    if ob.type == 'MESH': buckets.setdefault((ob.parent.name if ob.parent else 'Cabinet',ob.data.materials[0].name),[]).append(ob)
for (parent_name,material),parts in buckets.items():
    bpy.ops.object.select_all(action='DESELECT')
    for ob in parts: ob.select_set(True)
    bpy.context.view_layer.objects.active=parts[0]
    if len(parts)>1: bpy.ops.object.join()
    bpy.context.object.name=parent_name+' / '+material
bpy.ops.object.select_all(action='DESELECT')
for ob in collection.objects: ob.select_set(True)
bpy.context.view_layer.objects.active=next(ob for ob in collection.objects if ob.type=='MESH')
(root/'public/models').mkdir(exist_ok=True)
bpy.ops.export_scene.gltf(filepath=str(root/'public/models/mini-fridge.glb'),export_format='GLB',use_selection=True,export_apply=True,export_yup=True,export_extras=True)
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(root/'tools/blender/mini-fridge.blend'))
print('FRIDGE_EXPORTED',len(collection.objects),'nodes',sum(len(o.data.polygons) for o in collection.objects if o.type=='MESH'),'polygons',flush=True)
