"""Blender template-based authoring for native OpenSpidey character actors."""
bl_info = {'name': 'OpenSpidey Character Tools', 'author': 'OpenSpideyPS1 contributors',
           'version': (0, 1, 0), 'blender': (4, 5, 0), 'location': 'View3D > Sidebar > Spidey',
           'description': 'Import native templates, transfer weights and export segmented actors',
           'category': 'Import-Export'}

import base64
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import zipfile

import bpy
from bpy.props import BoolProperty, StringProperty, EnumProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

UNIT = 1800.0


def to_blender(p):
    x, y, z = p
    return Vector((x, z, -y)) / UNIT


def to_native(p):
    return [p.x * UNIT, -p.z * UNIT, p.y * UNIT]


def bone_name(i):
    return f'part_{i:03d}'


def run(command):
    result = subprocess.run([str(x) for x in command], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-3000:])


def import_template(filepath, multitool):
    """Read source rigid weights, including cross-part attachment ownership."""
    with tempfile.TemporaryDirectory(prefix='spidey-import-') as temp:
        output = Path(temp) / 'dump.json'
        run([multitool, 'psx-mesh-dump', filepath, '--json', output])
        data = json.loads(output.read_text())
    if data['Version'] != 4 or not data['Objects']:
        raise ValueError('Import a native v4 actor template with an object table')
    count = len(data['Objects'])
    # Spider-Man's two hand variants occupy separate mesh records. The custom
    # mesh supplies one hand pose, emitted into both records during export.
    hashes = {m['NameHash']: m['MeshIndex'] for m in data['Meshes'][:count]}
    alternates = {str(hashes[alternate]): hashes[primary]
                  for alternate, primary in [(0x08A2712E, 0xBC8D77AD), (0x7E8091DC, 0xCAAF975F)]
                  if alternate in hashes and primary in hashes}
    points, owners, faces, uv_faces, keys = [], [], [], [], {}
    for mesh in data['Meshes'][:count]:
        if str(mesh['MeshIndex']) in alternates:
            continue
        local = {}
        for v in mesh['Vertices']:
            if not v['AttachmentResolved']:
                raise ValueError('Template contains an unresolved attachment')
            key = (v['SourceMeshIndex'], v['SourceVertexIndex'])
            if key not in keys:
                keys[key] = len(points)
                points.append(to_blender([x * data['ScaleDivisor'] for x in v['WorldPosition'].values()]))
                owners.append(v['SourceMeshIndex'])
            local[v['VertexIndex']] = keys[key]
        for f in mesh['Faces']:
            for order in ([(0, 2, 1), (1, 2, 3)] if f['IsQuad'] else [(0, 2, 1)]):
                faces.append([local[f['Indices'][i]] for i in order])
                uv_faces.append([(f['TextureCoordinates'][i]['U'] / 127,
                                  1-f['TextureCoordinates'][i]['V'] / 127)
                                 if f['IsTextured'] else (0, 0) for i in order])
    mesh = bpy.data.meshes.new(Path(filepath).stem + ' template')
    mesh.from_pydata(points, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.collection.objects.link(obj)
    uv = mesh.uv_layers.new(name='UVMap')
    for p, coords in zip(mesh.polygons, uv_faces):
        for loop, coord in zip(p.loop_indices, coords):
            uv.data[loop].uv = coord
    arm = bpy.data.objects.new('Native template rig', bpy.data.armatures.new('Native hierarchy'))
    bpy.context.collection.objects.link(arm)
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    for i, entry in enumerate(data['Objects']):
        b = arm.data.edit_bones.new(bone_name(i))
        b.head = to_blender([x * data['ScaleDivisor'] for x in entry['Position'].values()])
        b.tail = b.head + Vector((0, 0, .06))
    for i, entry in enumerate(data['Objects']):
        parent = entry['ParentIndex']
        if parent >= 0:
            arm.data.edit_bones[bone_name(i)].parent = arm.data.edit_bones[bone_name(parent)]
    bpy.ops.object.mode_set(mode='OBJECT')
    for i in range(count):
        group = obj.vertex_groups.new(name=bone_name(i))
        ids = [v for v, owner in enumerate(owners) if owner == i]
        if ids:
            group.add(ids, 1.0, 'REPLACE')
    modifier = obj.modifiers.new('Native animation preview', 'ARMATURE')
    modifier.object = arm
    obj['spidey_template'] = True
    obj['spidey_dump'] = json.dumps(data)
    obj['spidey_donor'] = base64.b64encode(Path(filepath).read_bytes()).decode()
    obj['spidey_filename'] = Path(filepath).name
    obj['spidey_alternates'] = json.dumps(alternates)
    obj.show_wire = True
    arm.show_in_front = True
    for item in (obj, arm):
        item.lock_location = item.lock_rotation = item.lock_scale = (True, True, True)
    return obj, arm


def validate_template(template):
    rig = next(m.object for m in template.modifiers if m.type == 'ARMATURE')
    for obj in (template, rig):
        if any(abs(obj.matrix_world[i][j] - (1 if i == j else 0)) > 1e-6
               for i in range(4) for j in range(4)):
            raise ValueError('Keep template and rig object transforms unchanged; align the replacement instead')
    data = json.loads(template['spidey_dump'])
    for i, entry in enumerate(data['Objects']):
        bone = rig.data.bones.get(bone_name(i))
        expected = to_blender([x*data['ScaleDivisor'] for x in entry['Position'].values()])
        if bone is None or (bone.head_local-expected).length > 1e-5:
            raise ValueError('Template rest joints changed; reimport and use Pose Mode for alignment')
    return rig


def transfer_weights(template, target):
    """Nearest-surface barycentric transfer; the user aligns the meshes first."""
    rig = validate_template(template)
    # Freeze the artist's visible alignment pose before replacing the source rig.
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    baked = bpy.data.meshes.new_from_object(evaluated)
    old = target.data
    target.modifiers.clear()
    target.data = baked
    if old.users == 0:
        bpy.data.meshes.remove(old)
    ref = template.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    ref.calc_loop_triangles()
    points = [template.matrix_world @ v.co for v in ref.vertices]
    triangles = [tuple(t.vertices) for t in ref.loop_triangles]
    tree = BVHTree.FromPolygons(points, triangles, all_triangles=True)
    template.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
    names = [g.name for g in template.vertex_groups]
    for g in list(target.vertex_groups):
        target.vertex_groups.remove(g)
    for name in names:
        target.vertex_groups.new(name=name)
    for v in target.data.vertices:
        hit, _, index, _ = tree.find_nearest(target.matrix_world @ v.co)
        if hit is None:
            raise ValueError('Template has no usable surface')
        ids = triangles[index]
        bary = barycentric_transform(hit, *(points[i] for i in ids),
                                     Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        weights = {}
        for i, amount in zip(ids, bary):
            for g in template.data.vertices[i].groups:
                weights[g.group] = weights.get(g.group, 0) + max(0, amount) * g.weight
        total = sum(weights.values())
        for group, weight in weights.items():
            if weight > 1e-8:
                target.vertex_groups[group].add([v.index], weight / total, 'REPLACE')
        # Transfer can happen in a spread pose to keep hands away from hips.
        # Undo the weighted template pose to obtain the replacement's rest mesh.
        skin = Matrix(((0,0,0,0),)*4)
        for group, weight in weights.items():
            bone = rig.pose.bones[names[group]]
            skin += (rig.matrix_world @ bone.matrix @ bone.bone.matrix_local.inverted()
                     @ rig.matrix_world.inverted()) * (weight/total)
        v.co = target.matrix_world.inverted() @ skin.inverted() @ (target.matrix_world @ v.co)
    for m in list(target.modifiers):
        if m.type == 'ARMATURE':
            target.modifiers.remove(m)
    target.modifiers.new('Native animation preview', 'ARMATURE').object = rig


def collect_geometry(obj, count):
    obj.data.calc_loop_triangles()
    if not obj.data.uv_layers.active:
        raise ValueError('Replacement requires a UV map')
    vertices, owners, aliases, lookup = [], [], {}, {}
    for v in obj.data.vertices:
        weights = {}
        for g in v.groups:
            name = obj.vertex_groups[g.group].name
            if name.startswith('part_') and name[5:].isdigit() and g.weight > 0:
                i = int(name[5:])
                if i >= count:
                    raise ValueError('Vertex group refers to a part outside the template')
                weights[i] = weights.get(i, 0) + g.weight
        if not weights:
            raise ValueError(f'Vertex {v.index} has no native weights; transfer weights first')
        owner = max(weights, key=weights.get)
        point = to_native(obj.matrix_world @ v.co)
        key = (tuple(round(x, 4) for x in point), owner)
        if key not in lookup:
            lookup[key] = len(vertices)
            vertices.append(point)
            owners.append(owner)
        aliases[v.index] = lookup[key]
    uv = obj.data.uv_layers.active.data
    faces = []
    for t in obj.data.loop_triangles:
        ids = [aliases[i] for i in t.vertices]
        if len(set(ids)) < 3:
            continue
        coords = [list(uv[i].uv) for i in t.loops]
        for axis in (0, 1):
            offset = math.floor(min(c[axis] for c in coords) + 1e-6)
            if max(c[axis] for c in coords) - offset > 1.000001:
                raise ValueError(f'A UV triangle crosses atlas tiles: {coords}; split it or bake to one atlas')
            for coord in coords:
                coord[axis] -= offset
        faces.append({'v': ids, 'uv': coords})
    parts = [set() for _ in range(count)]
    for i, owner in enumerate(owners):
        parts[owner].add(i)
    for face in faces:
        parts[max(owners[i] for i in face['v'])].update(face['v'])
    return dict(vertices=vertices, owners=owners, faces=faces), [len(p) for p in parts]


def export_actor(template, target, image, output, repository, python, multitool, reduce=True):
    """Export a copy; the artist's original mesh and weights stay untouched."""
    output = Path(output)
    if output.exists():
        raise ValueError('Choose a fresh output directory')
    validate_template(template)
    data = json.loads(template['spidey_dump'])
    count = len(data['Objects'])
    copy = target.copy()
    copy.data = target.data.copy()
    bpy.context.collection.objects.link(copy)
    try:
        # Bake the visible model, including an artist-authored pose, into bind geometry.
        native_rig = next(m.object for m in template.modifiers if m.type == 'ARMATURE')
        for modifier in list(copy.modifiers):
            if modifier.type == 'ARMATURE' and modifier.object == native_rig:
                copy.modifiers.remove(modifier)
        evaluated = copy.evaluated_get(bpy.context.evaluated_depsgraph_get())
        baked = bpy.data.meshes.new_from_object(evaluated)
        copy.modifiers.clear()
        old = copy.data
        copy.data = baked
        bpy.data.meshes.remove(old)
        if not baked.uv_layers.active:
            raise ValueError('Replacement requires a UV map')
        uv = baked.uv_layers.active.data
        for polygon in baked.polygons:
            for axis in (0,1):
                values = [uv[i].uv[axis] for i in polygon.loop_indices]
                shift = math.floor(min(values)+1e-6)
                if max(values)-shift > 1.000001:
                    raise ValueError('A source UV polygon crosses atlas tiles; split or bake it first')
                for i in polygon.loop_indices:
                    uv[i].uv[axis] -= shift
        original_triangles = len(baked.polygons)
        iterations = 0
        clamped_uvs = 0
        while True:
            fit, budgets = collect_geometry(copy, count)
            if max(budgets) <= 256:
                break
            if not reduce or iterations >= 16:
                raise ValueError(f'Native part vertex limit exceeded: {budgets}; reduce topology')
            bpy.ops.object.select_all(action='DESELECT')
            copy.select_set(True)
            bpy.context.view_layer.objects.active = copy
            m = copy.modifiers.new('Native export budget', 'DECIMATE')
            m.ratio = .85
            m.use_collapse_triangulate = True
            bpy.ops.object.modifier_apply(modifier=m.name)
            # Collapse can extrapolate corner UVs outside the source atlas.
            # Keep those newly generated coordinates inside its boundary.
            for corner in copy.data.uv_layers.active.data:
                for axis in (0,1):
                    value = corner.uv[axis]
                    if value < 0 or value > 1:
                        clamped_uvs += 1
                        corner.uv[axis] = min(1,max(0,value))
            iterations += 1
        fit['offsets'] = {str(m['MeshIndex']): [x * data['ScaleDivisor'] for x in
                         data['Objects'][m['ObjectIndex']]['Position'].values()] for m in data['Meshes'][:count]}
        fit['alternateParts'] = json.loads(template.get('spidey_alternates', '{}'))
        fit['usedTemplateTextureHashes'] = sorted({f['TextureHash'] for m in data['Meshes']
                                                   for f in m['Faces'] if f['IsTextured']})
        output.mkdir(parents=True)
        (output / 'donor.psx').write_bytes(base64.b64decode(template['spidey_donor']))
        (output / 'fitted.json').write_text(json.dumps(fit))
        texture = output / 'Body_D_rgb.tga'
        previous = image.filepath_raw, image.file_format
        try:
            image.filepath_raw = str(texture)
            image.file_format = 'TARGA'
            image.save()
        finally:
            image.filepath_raw, image.file_format = previous
        filename = Path(template['spidey_filename']).name
        run([python, Path(repository) / 'dreamcast/tools/pack_unlimited_actor.py',
             '--source', output, '--output', output, '--id', 'blender-' + Path(filename).stem,
             '--name', 'Blender Character', '--opaque-diffuse', '--template-layout', '--actor-file', filename])
        run([multitool, 'psx-mesh-dump', output / 'assets' / filename, '--json', output / 'validated.json'])
        check = json.loads((output / 'validated.json').read_text())
        assert check['Objects'] == data['Objects'], 'Native hierarchy changed'
        assert len(check['Meshes']) == count
        assert all(m['LodNextMeshIndex'] == 65535 for m in check['Meshes'])
        assert all(m['VertexCount'] <= 256 and not m['StitchFailureCount'] and
                   all(not f.get('RejectionReason') for f in m['FaceReads']) for m in check['Meshes'])
        extra = sum(check['Meshes'][int(i)]['FaceCount'] for i in fit['alternateParts'])
        assert sum(m['FaceCount'] for m in check['Meshes']) == len(fit['faces']) + extra
        import struct
        def animation_tags(raw):
            start = cursor = struct.unpack_from('<I', raw, 4)[0]
            while struct.unpack_from('<I', raw, cursor)[0] != 0xFFFFFFFF:
                cursor += 8 + struct.unpack_from('<I', raw, cursor + 4)[0]
            return raw[start:cursor+4]
        original_tags = animation_tags(base64.b64decode(template['spidey_donor']))
        assert animation_tags((output / 'assets' / filename).read_bytes()) == original_tags
        report = {'status': 'structural-pass-native-review-required', 'sourcePolygons': original_triangles,
                  'exportedTriangles': len(fit['faces']), 'partVertices': budgets,
                  'reductionSteps': iterations, 'templateSha256': hashlib.sha256(base64.b64decode(template['spidey_donor'])).hexdigest(),
                  'decimationUvBoundaryClamps': clamped_uvs,
                  'actorSha256': hashlib.sha256((output / 'assets' / filename).read_bytes()).hexdigest(),
                  'hierarchyPreserved': True, 'animationTagsPreserved': True,
                  'sourceMeshRecords': len(data['Meshes']), 'exportedMeshRecords': count,
                  'lodPolicy': 'One terminal mesh per object; shared seams remain valid at every distance',
                  'animationTagsSha256': hashlib.sha256(original_tags).hexdigest(),
                  'policy': 'Dominant rigid weights and shared native seam references'}
        (output / 'blender-report.json').write_text(json.dumps(report, indent=2))
        return report
    finally:
        mesh = copy.data
        bpy.data.objects.remove(copy, do_unlink=True)
        bpy.data.meshes.remove(mesh)


class SPIDEY_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    repository: StringProperty(name='OpenSpidey repository', subtype='DIR_PATH')
    python: StringProperty(name='Python executable (with Pillow)', subtype='FILE_PATH')
    multitool: StringProperty(name='NeversoftMultitool executable', subtype='FILE_PATH')

    def draw(self, context):
        for name in ('repository', 'python', 'multitool'):
            self.layout.prop(self, name)


def preferences(context):
    return context.preferences.addons[__package__].preferences


def template_in_scene(context):
    found = [o for o in context.scene.objects if o.get('spidey_template')]
    if len(found) != 1:
        raise ValueError('Keep exactly one imported template in the scene')
    return found[0]


class SPIDEY_Import(bpy.types.Operator, ImportHelper):
    bl_idname = 'spidey.import_template'
    bl_label = 'Import PSX Character Template'
    filename_ext = '.psx'
    filter_glob: StringProperty(default='*.psx', options={'HIDDEN'})

    def execute(self, context):
        try:
            import_template(self.filepath, preferences(context).multitool)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


class SPIDEY_Builtin(bpy.types.Operator):
    bl_idname = 'spidey.import_builtin'
    bl_label = 'Import Bundled Character Template'
    character: EnumProperty(name='Character', items=[(x['name'], Path(x['name']).stem, '')
        for x in json.loads((Path(__file__).parent/'templates.json').read_text())])

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            p = preferences(context)
            with tempfile.TemporaryDirectory(prefix='spidey-template-') as td:
                path = Path(td)/self.character
                with zipfile.ZipFile(Path(p.repository)/'spiderman/port/bundled/runtime-assets.zip') as archive:
                    path.write_bytes(archive.read(self.character))
                import_template(path, p.multitool)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


class SPIDEY_Transfer(bpy.types.Operator):
    bl_idname = 'spidey.transfer_weights'
    bl_label = 'Transfer Template Weights to Active Mesh'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            template = template_in_scene(context)
            target = context.active_object
            if target is None or target.type != 'MESH' or target == template:
                raise ValueError('Select the aligned replacement mesh')
            transfer_weights(template, target)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


class SPIDEY_Export(bpy.types.Operator, ExportHelper):
    bl_idname = 'spidey.export_actor'
    bl_label = 'Export Native Character Package'
    filename_ext = '.spidey'
    reduce: BoolProperty(name='Reduce copy to native vertex budgets', default=True)

    def execute(self, context):
        try:
            template = template_in_scene(context)
            target = context.active_object
            if target is None or target.type != 'MESH' or target == template:
                raise ValueError('Select the replacement mesh')
            images = {n.image for s in target.material_slots if s.material and s.material.use_nodes
                      for n in s.material.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image}
            if len(images) != 1:
                raise ValueError('Use one diffuse image atlas; bake other maps/materials first')
            p = preferences(context)
            export_actor(template, target, images.pop(), self.filepath, p.repository, p.python, p.multitool, self.reduce)
            self.report({'INFO'}, 'Native package exported; review it in game before installation')
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


class SPIDEY_Panel(bpy.types.Panel):
    bl_label = 'OpenSpidey Characters'
    bl_idname = 'SPIDEY_PT_character'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Spidey'

    def draw(self, context):
        self.layout.operator('spidey.import_builtin')
        self.layout.operator('spidey.import_template')
        self.layout.label(text='Spread touching limbs in Pose Mode, then align your mesh.')
        self.layout.operator('spidey.transfer_weights')
        self.layout.operator('spidey.export_actor')


classes = (SPIDEY_Preferences, SPIDEY_Import, SPIDEY_Builtin, SPIDEY_Transfer, SPIDEY_Export, SPIDEY_Panel)


def import_menu(self, context):
    self.layout.operator(SPIDEY_Import.bl_idname, text='OpenSpidey Character Template (.psx)')


def export_menu(self, context):
    self.layout.operator(SPIDEY_Export.bl_idname, text='OpenSpidey Character Package (.spidey)')


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(import_menu)
    bpy.types.TOPBAR_MT_file_export.append(export_menu)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(import_menu)
    bpy.types.TOPBAR_MT_file_export.remove(export_menu)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
