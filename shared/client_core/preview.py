"""
BeezClient Preview Generator

Generates blurred preview images for digital assets in the marketplace.
These previews protect the original content while showing potential buyers
a preview of what they're purchasing.

Supported file types:
- Images: JPEG, PNG, GIF, WebP, BMP, TIFF
- Documents: PDF (first page thumbnail)
"""

import io
import os
import hashlib
import base64
from typing import Optional
from dataclasses import dataclass

# PIL for image processing
try:
    from PIL import Image, ImageFilter, ImageDraw, ImageFont
    # Raise the decompression bomb limit for large PDFs
    # Preview pipeline resizes immediately after loading, so this is safe
    Image.MAX_IMAGE_PIXELS = 300_000_000
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[PREVIEW] WARNING: PIL/Pillow not available - install with: pip install Pillow", flush=True)

# PyMuPDF for PDF rendering — no system dependency required
# Since v1.24 the canonical import is `import pymupdf`; the legacy
# `import fitz` alias may be absent in Briefcase-packaged macOS builds.
try:
    import pymupdf
    PYMUPDF_AVAILABLE = True
except ImportError:
    try:
        import fitz as pymupdf
        PYMUPDF_AVAILABLE = True
    except ImportError:
        PYMUPDF_AVAILABLE = False
        print("[PREVIEW] WARNING: PyMuPDF not available — PDF previews disabled. "
              "Install with: pip install pymupdf", flush=True)

# pdf2image as fallback (requires system poppler-utils)
try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

if not PYMUPDF_AVAILABLE and not PDF2IMAGE_AVAILABLE:
    print("[PREVIEW] WARNING: No PDF renderer available. "
          "Install pymupdf (pip install pymupdf) or pdf2image + poppler-utils", flush=True)


@dataclass
class PreviewConfig:
    """Configuration for preview generation."""
    max_width: int = 800
    max_height: int = 600
    blur_radius: int = 12  # Light blur - enough to protect details, still recognizable
    quality: int = 70  # JPEG quality
    watermark_text: str = "BEEZ PREVIEW"
    watermark_opacity: int = 80  # 0-255 (subtle watermark)
    output_format: str = "JPEG"


@dataclass
class PreviewResult:
    """Result of preview generation."""
    success: bool
    preview_data: Optional[bytes] = None
    preview_hash: Optional[str] = None
    width: int = 0
    height: int = 0
    format: str = "JPEG"
    error: Optional[str] = None


class PreviewGenerator:
    """
    Generates blurred preview images for marketplace listings.
    
    The preview protects the original content by:
    1. Applying strong Gaussian blur
    2. Adding a watermark
    3. Reducing quality
    4. Resizing to smaller dimensions
    """
    
    # Supported image extensions
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif'}
    
    # Supported document extensions
    DOCUMENT_EXTENSIONS = {'.pdf'}
    
    def __init__(self, wallet=None, config: PreviewConfig = None):
        """
        Initialize preview generator.
        
        Args:
            wallet: Optional wallet for deterministic seed generation
            config: Optional preview configuration
        """
        self.wallet = wallet
        self.config = config or PreviewConfig()
        
        # Derive seed from wallet for deterministic operations
        if wallet and hasattr(wallet, 'privkey'):
            self.seed = int.from_bytes(
                hashlib.sha256(wallet.privkey + b"preview_seed").digest()[:8],
                byteorder='big'
            )
        else:
            self.seed = None
    
    def _get_blur_radius(self, file_hash: Optional[str] = None) -> int:
        """Get blur radius, optionally varying by file hash for uniqueness."""
        base_radius = self.config.blur_radius
        
        if self.seed and file_hash:
            # Add slight variation based on file (±5)
            variation_seed = int(hashlib.sha256(
                file_hash.encode() + str(self.seed).encode()
            ).hexdigest()[:4], 16) % 10 - 5
            return max(15, base_radius + variation_seed)
        
        return base_radius
    
    def _resize_image(self, image: "Image.Image") -> "Image.Image":
        """Resize image to fit within max dimensions while preserving aspect ratio."""
        if not PIL_AVAILABLE:
            return image
            
        width, height = image.size
        max_w, max_h = self.config.max_width, self.config.max_height
        
        if width <= max_w and height <= max_h:
            return image
        
        scale = min(max_w / width, max_h / height)
        new_width = int(width * scale)
        new_height = int(height * scale)
        
        return image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    def _apply_blur(self, image: "Image.Image", radius: int) -> "Image.Image":
        """Apply Gaussian blur to image."""
        if not PIL_AVAILABLE:
            return image
        return image.filter(ImageFilter.GaussianBlur(radius=radius))
    
    def _add_watermark(self, image: "Image.Image") -> "Image.Image":
        """Add watermark text to blurred image."""
        if not PIL_AVAILABLE or not self.config.watermark_text:
            return image
        
        watermarked = image.copy()
        draw = ImageDraw.Draw(watermarked)
        width, height = watermarked.size
        
        # Try to use a nice font, fall back to default
        try:
            font_size = max(20, min(width, height) // 15)
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except:
            try:
                font = ImageFont.truetype("arial.ttf", 30)
            except:
                font = ImageFont.load_default()
        
        text = self.config.watermark_text
        
        # Get text bounding box
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        except AttributeError:
            text_width, text_height = draw.textsize(text, font=font)
        
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        # Create overlay for transparency
        overlay = Image.new('RGBA', watermarked.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        
        opacity = self.config.watermark_opacity
        overlay_draw.text((x, y), text, font=font, fill=(255, 255, 255, opacity))
        
        # Add diagonal watermarks
        for offset_y in range(-height, height * 2, 150):
            for offset_x in range(-width, width * 2, 300):
                overlay_draw.text(
                    (offset_x, offset_y), 
                    text, 
                    font=font, 
                    fill=(255, 255, 255, opacity // 3)
                )
        
        if watermarked.mode != 'RGBA':
            watermarked = watermarked.convert('RGBA')
        
        watermarked = Image.alpha_composite(watermarked, overlay)
        
        return watermarked
    
    def _convert_pdf_to_image(self, pdf_content: bytes) -> Optional["Image.Image"]:
        """Convert first page of PDF to image, constrained to preview dimensions.

        Tries PyMuPDF first (no system dependency), falls back to pdf2image.
        """
        img = None

        if PYMUPDF_AVAILABLE:
            try:
                doc = pymupdf.open(stream=pdf_content, filetype="pdf")
                page = doc[0]
                # Render at a resolution that fits our preview dimensions
                zoom = min(self.config.max_width / page.rect.width,
                           self.config.max_height / page.rect.height,
                           2.0)
                mat = pymupdf.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                doc.close()
                print(f"[PREVIEW] PDF rendered via PyMuPDF: {img.size[0]}x{img.size[1]}", flush=True)
            except Exception as e:
                print(f"[PREVIEW] PyMuPDF PDF render failed: {e}", flush=True)
                img = None

        if img is None and PDF2IMAGE_AVAILABLE:
            try:
                images = convert_from_bytes(
                    pdf_content,
                    first_page=1,
                    last_page=1,
                    size=(self.config.max_width, self.config.max_height)
                )
                if images:
                    img = images[0]
                    print(f"[PREVIEW] PDF rendered via pdf2image: {img.size[0]}x{img.size[1]}", flush=True)
            except Exception as e:
                print(f"[PREVIEW] pdf2image PDF render failed: {e}", flush=True)
                img = None

        if img is None:
            print("[PREVIEW] All PDF renderers failed", flush=True)
            return None

        w, h = img.size
        if w * h > 50_000_000:
            scale = (50_000_000 / (w * h)) ** 0.5
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            print(f"[PREVIEW] Resized large PDF render: {w}x{h} -> {img.size[0]}x{img.size[1]}", flush=True)

        return img
    
    def generate_preview(
        self,
        file_content: bytes,
        file_extension: str,
        file_hash: Optional[str] = None
    ) -> PreviewResult:
        """
        Generate a blurred preview image for the given file content.
        
        Args:
            file_content: Original file bytes (decrypted)
            file_extension: File extension (e.g., '.jpg', '.pdf')
            file_hash: Optional hash for variation
            
        Returns:
            PreviewResult with preview data and metadata
        """
        if not PIL_AVAILABLE:
            return PreviewResult(success=False, error="PIL/Pillow not available")
        
        ext = file_extension.lower()
        
        try:
            # Step 1: Load or convert to image
            if ext in self.IMAGE_EXTENSIONS:
                image = Image.open(io.BytesIO(file_content))
            elif ext in self.DOCUMENT_EXTENSIONS:
                if ext == '.pdf':
                    image = self._convert_pdf_to_image(file_content)
                    if image is None:
                        return PreviewResult(success=False, error="Failed to convert PDF")
                else:
                    return PreviewResult(success=False, error=f"Unsupported document: {ext}")
            else:
                return PreviewResult(success=False, error=f"Unsupported file type: {ext}")
            
            # Ensure RGB mode for JPEG output
            if image.mode in ('RGBA', 'P'):
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Step 2: Resize to preview dimensions
            image = self._resize_image(image)
            
            # Step 3: Apply blur
            blur_radius = self._get_blur_radius(file_hash)
            image = self._apply_blur(image, blur_radius)
            
            # Step 4: Add watermark
            if image.mode != 'RGBA':
                image = image.convert('RGBA')
            image = self._add_watermark(image)
            
            # Convert back to RGB for JPEG
            if image.mode == 'RGBA':
                background = Image.new('RGB', image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[-1])
                image = background
            
            # Step 5: Save to bytes
            output = io.BytesIO()
            image.save(
                output,
                format=self.config.output_format,
                quality=self.config.quality,
                optimize=True
            )
            preview_data = output.getvalue()
            
            preview_hash = hashlib.sha256(preview_data).hexdigest()
            
            return PreviewResult(
                success=True,
                preview_data=preview_data,
                preview_hash=preview_hash,
                width=image.size[0],
                height=image.size[1],
                format=self.config.output_format
            )
            
        except Exception as e:
            return PreviewResult(success=False, error=str(e))
    
    def generate_preview_from_file(self, file_path: str) -> PreviewResult:
        """Generate preview from a file path."""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            
            ext = os.path.splitext(file_path)[1]
            file_hash = hashlib.sha256(content).hexdigest()
            
            return self.generate_preview(content, ext, file_hash)
            
        except Exception as e:
            return PreviewResult(success=False, error=f"Failed to read file: {e}")
    
    @staticmethod
    def is_previewable(file_extension: str) -> bool:
        """Check if a file type can have a preview generated."""
        ext = file_extension.lower()
        if not ext.startswith('.'):
            ext = '.' + ext
        return ext in PreviewGenerator.IMAGE_EXTENSIONS or ext in PreviewGenerator.DOCUMENT_EXTENSIONS


def encode_preview_base64(preview_data: bytes) -> str:
    """Encode preview data to base64 for JSON storage/transport."""
    return base64.b64encode(preview_data).decode('utf-8')


def decode_preview_base64(preview_b64: str) -> bytes:
    """Decode base64 preview data."""
    return base64.b64decode(preview_b64)
