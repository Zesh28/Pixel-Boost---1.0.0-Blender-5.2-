bl_info = {
    "name": "PixelBoost (NCNN)",
    "author": "Zesh_28",
    "version": (1, 0, 0),
    "blender": (5, 2, 0),
    "location": "Properties > Output > PixelBoost",
    "description": "AI video upscaling for renders (NCNN, portable)",
    "category": "Render",
}

import bpy
import os
import subprocess

# === ПУТИ (относительно папки аддона) ===
ADDON_DIR = os.path.dirname(os.path.abspath(file))
CORE_DIR = os.path.join(ADDON_DIR, "core")
REALESRGAN_EXE = os.path.join(CORE_DIR, "realesrgan-ncnn-vulkan.exe")
FFMPEG_EXE = os.path.join(CORE_DIR, "ffmpeg.exe")
MODELS_DIR = os.path.join(CORE_DIR, "models")

# === ПРЕСЕТЫ ===
PRESETS = {
    '1080p': {'base': (960, 540), 'scale': 2, 'result': (1920, 1080)},
    '2K':    {'base': (854, 480), 'scale': 3, 'result': (2562, 1440)},
    '4K':    {'base': (960, 540), 'scale': 4, 'result': (3840, 2160)},
}

# === ФОРМАТ ИМЕНИ КАДРА ===
FRAME_PATTERN = "frame_%08d.png"
FRAME_TEMPLATE = "frame_########"


# === СВОЙСТВА ===
class PIXELBOOST_Properties(bpy.types.PropertyGroup):
    enable: bpy.props.BoolProperty(name="Enable PixelBoost", default=False)
    preset: bpy.props.EnumProperty(
        name="Output Preset",
        items=[
            ('1080p', "1080p (2x)", "960x540 -> 1920x1080"),
            ('2K', "2K (3x)", "854x480 -> 2562x1440"),
            ('4K', "4K (4x)", "960x540 -> 3840x2160"),
        ],
        default='1080p'
    )
    make_mp4: bpy.props.BoolProperty(name="Build MP4 after upscale", default=True)
    video_fps: bpy.props.IntProperty(name="FPS", default=60, min=1, max=240)
    video_crf: bpy.props.IntProperty(name="CRF (quality)", default=18, min=0, max=51)


# === UI ПАНЕЛЬ ===
class PIXELBOOST_PT_panel(bpy.types.Panel):
    bl_label = "PixelBoost"
    bl_idname = "PIXELBOOST_PT_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "output"

    def draw(self, context):
        layout = self.layout
        props = context.scene.pixelboost
        render = context.scene.render

        layout.prop(props, "enable")
        if props.enable:
            layout.prop(props, "preset", text="")
            preset = PRESETS[props.preset]

            box = layout.box()
            box.label(text=f"Render: {preset['base'][0]}x{preset['base'][1]}")
            box.label(text=f"Upscale: {preset['scale']}x -> {preset['result'][0]}x{preset['result'][1]}", icon='INFO')

            layout.operator("pixelboost.apply_preset", icon='FILE_REFRESH')
            layout.operator("pixelboost.set_naming", icon='SORTALPHA', text="Set Frame Naming (8 digits)")

            if (render.resolution_x, render.resolution_y) != preset['base']:
                layout.label(text="Resolution mismatch!", icon='ERROR')

            layout.separator()
            layout.label(text="Video Output:", icon='FILE_MOVIE')
            layout.prop(props, "make_mp4")
            if props.make_mp4:
                layout.prop(props, "video_fps")
                layout.prop(props, "video_crf")

            layout.separator()
            layout.operator("pixelboost.check_setup", icon='CHECKMARK', text="Check Setup")


# === ВСПОМОГАТЕЛЬНАЯ: ОПРЕДЕЛИТЬ ПАПКУ ВЫВОДА ===
def get_output_dir(scene):
    raw = scene.render.filepath
    if not raw:
        return None
    path = bpy.path.abspath(raw)
    if not path:
        return None

    # Если это файл с расширением — берём родительскую папку
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.png', '.jpg', '.jpeg', '.exr', '.tiff', '.tif', '.bmp'):
        path = os.path.dirname(path)

    # Если есть шаблон кадра (frame_########) — обрезаем И берём родительскую папку
    if '#' in path:
        path = os.path.dirname(path.split('#')[0])

    path = path.rstrip(os.sep).rstrip('/')

    if not path or not os.path.isdir(path):
        return None
    return path


# === СБОРКА MP4 ===
def build_mp4(frames_dir, output_mp4, fps, crf, ffmpeg_bin):
    if not ffmpeg_bin or not os.path.exists(ffmpeg_bin):
        print(f"[PixelBoost] ERROR: FFmpeg not found: {ffmpeg_bin}")
        return False sample = os.path.join(frames_dir, "frame_00000001.png")
    if not os.path.exists(sample):
        print(f"[PixelBoost] ERROR: expected frame not found: {sample}")
        print(f"[PixelBoost] Make sure you clicked 'Set Frame Naming' before rendering")
        return False

    cmd = [
        ffmpeg_bin, "-y",
        "-framerate", str(fps),
        "-start_number", "1",
        "-i", os.path.join(frames_dir, FRAME_PATTERN),
        "-c:v", "libx264",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        output_mp4
    ]

    print(f"[PixelBoost] Building MP4: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode != 0:
            print(f"[PixelBoost] FFmpeg STDERR: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"[PixelBoost] MP4 build crashed: {e}")
        return False


# === ОПЕРАТОР: ПРИМЕНИТЬ ПРЕСЕТ ===
class PIXELBOOST_OT_apply_preset(bpy.types.Operator):
    bl_idname = "pixelboost.apply_preset"
    bl_label = "Apply Preset"

    def execute(self, context):
        try:
            preset = PRESETS[context.scene.pixelboost.preset]
        except KeyError:
            self.report({'ERROR'}, "Invalid preset selected")
            return {'CANCELLED'}
        render = context.scene.render
        render.resolution_x = preset['base'][0]
        render.resolution_y = preset['base'][1]
        render.resolution_percentage = 100
        self.report({'INFO'}, f"Render set to {preset['base'][0]}x{preset['base'][1]}")
        return {'FINISHED'}


# === ОПЕРАТОР: SET FRAME NAMING ===
class PIXELBOOST_OT_set_naming(bpy.types.Operator):
    bl_idname = "pixelboost.set_naming"
    bl_label = "Set Frame Naming"
    bl_description = "Force frame filenames to frame_00000001.png format"

    def execute(self, context):
        render = context.scene.render
        current = bpy.path.abspath(render.filepath)
        if not current:
            self.report({'ERROR'}, "Output path is empty. Set it in Properties > Output.")
            return {'CANCELLED'}
        if os.path.splitext(current)[1].lower() in ('.png', '.jpg', '.jpeg', '.exr'):
            current = os.path.dirname(current)
        if '#' in current:
            current = current.split('#')[0]
        current = current.rstrip(os.sep).rstrip('/')
        new_path = os.path.join(current, FRAME_TEMPLATE)
        render.filepath = new_path
        self.report({'INFO'}, f"Frame naming set: {FRAME_TEMPLATE}")
        return {'FINISHED'}


# === ОПЕРАТОР: CHECK SETUP ===
class PIXELBOOST_OT_check_setup(bpy.types.Operator):
    bl_idname = "pixelboost.check_setup"
    bl_label = "Check Setup"

    def execute(self, context):
        props = context.scene.pixelboost
        problems = []

        if not os.path.exists(REALESRGAN_EXE):
            problems.append(f"NCNN executable not found: {REALESRGAN_EXE}")
        if props.make_mp4 and not os.path.exists(FFMPEG_EXE):
            problems.append(f"FFmpeg not found: {FFMPEG_EXE}")

        for scale in ['x2', 'x3', 'x4']:
            model_param = os.path.join(MODELS_DIR, f"realesr-animevideov3-{scale}.param")
            model_bin = os.path.join(MODELS_DIR, f"realesr-animevideov3-{scale}.bin")
            if not os.path.exists(model_param) or not os.path.exists(model_bin):
                problems.append(f"Model files missing for: realesr-animevideov3-{scale}")

        out_dir = get_output_dir(context.scene)
        if out_dir is None:
            problems.append("Output path invalid (Properties > Output)")

        if problems:
            msg = " | ".join(problems)
            self.report({'WARNING'}, msg)
            print(f"[PixelBoost] Setup issues: {msg}")
        else:
            self.report({'INFO'}, "PixelBoost: everything OK!")
            print("[PixelBoost] Setup OK")
        return {'FINISHED'} # === АПСКЕЙЛ (NCNN) ===
def upscale_sequence(input_dir, output_dir, scale):
    if not os.path.exists(REALESRGAN_EXE):
        print(f"[PixelBoost] ERROR: executable not found: {REALESRGAN_EXE}")
        return False
    if not os.path.isdir(input_dir):
        print(f"[PixelBoost] ERROR: input dir not found: {input_dir}")
        return False

    frames = [f for f in os.listdir(input_dir) if f.lower().endswith('.png')]
    if not frames:
        print(f"[PixelBoost] ERROR: no PNG files in {input_dir}")
        return False

    os.makedirs(output_dir, exist_ok=True)

    model_name = f"realesr-animevideov3-x{scale}"

    cmd = [
        REALESRGAN_EXE,
        "-i", input_dir,
        "-o", output_dir,
        "-n", model_name,
        "-s", str(scale),
        "-t", "0",
        "-g", "0",
        "-f", "png"
    ]

    print(f"[PixelBoost] Running NCNN: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode != 0:
            print(f"[PixelBoost] NCNN STDERR: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"[PixelBoost] NCNN crashed: {e}")
        return False


# === HANDLER ===
@bpy.app.handlers.persistent
def pixelboost_render_complete(scene):
    try:
        props = scene.pixelboost
    except AttributeError:
        return
    if not props.enable:
        return

    preset = PRESETS.get(props.preset)
    if not preset:
        return

    output_dir = get_output_dir(scene)
    if output_dir is None:
        print("[PixelBoost] ERROR: cannot determine output directory")
        return

    boosted_dir = output_dir + "_boosted"
    print(f"[PixelBoost] Render done. Upscaling to {boosted_dir} ({preset['scale']}x)")

    if not upscale_sequence(output_dir, boosted_dir, preset['scale']):
        print("[PixelBoost] Upscale failed")
        return

    print(f"[PixelBoost] Upscale done. Frames in: {boosted_dir}")

    if props.make_mp4:
        output_mp4 = output_dir + ".mp4"
        if build_mp4(boosted_dir, output_mp4, props.video_fps, props.video_crf, FFMPEG_EXE):
            print(f"[PixelBoost] MP4 saved: {output_mp4}")
        else:
            print("[PixelBoost] MP4 build failed")


# === РЕГИСТРАЦИЯ ===
classes = (
    PIXELBOOST_Properties,
    PIXELBOOST_PT_panel,
    PIXELBOOST_OT_apply_preset,
    PIXELBOOST_OT_set_naming,
    PIXELBOOST_OT_check_setup,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.pixelboost = bpy.props.PointerProperty(type=PIXELBOOST_Properties)
    if pixelboost_render_complete not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(pixelboost_render_complete)


def unregister():
    if pixelboost_render_complete in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(pixelboost_render_complete)
    if hasattr(bpy.types.Scene, "pixelboost"):
        del bpy.types.Scene.pixelboost
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if name == "main":
    register()
