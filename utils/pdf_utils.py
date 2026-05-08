"""图片合成 PDF 与临时文件清理。"""

from pathlib import Path

from PIL import Image


def images_to_pdf(image_files: list[Path], pdf_path: Path) -> None:
    """将图片顺序合并为单个 PDF。"""
    if not image_files:
        raise ValueError("没有可用于合成 PDF 的图片")

    images = []
    for img_file in image_files:
        img = Image.open(img_file)
        if img.mode != "RGB":
            rgb_img = img.convert("RGB")
            img.close()
            images.append(rgb_img)
        else:
            images.append(img)

    try:
        if images:
            first_img, *rest_imgs = images
            first_img.save(pdf_path, save_all=True, append_images=rest_imgs)
    finally:
        for img in images:
            img.close()


def cleanup_images(image_files: list[Path], image_dir: Path) -> None:
    """可选清理临时图片与空目录。"""
    for img_file in image_files:
        try:
            img_file.unlink(missing_ok=True)
        except Exception as exc:
            print(f"删除图片失败: {img_file.name}: {exc}")
    try:
        next(image_dir.iterdir())
    except StopIteration:
        try:
            image_dir.rmdir()
        except Exception as exc:
            print(f"删除空目录失败: {image_dir}: {exc}")
    except Exception:
        pass
