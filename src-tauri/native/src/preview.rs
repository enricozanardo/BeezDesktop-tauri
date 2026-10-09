use std::io::Cursor;

use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use image::codecs::jpeg::JpegEncoder;
use image::imageops::FilterType;
use serde_json::{json, Value};

use crate::crypto::sha256_hex;

const MAX_W: u32 = 480;
const MAX_H: u32 = 360;
const BLUR_SIGMA: f32 = 7.0;
const JPEG_QUALITY: u8 = 60;

pub const PREVIEWABLE: &[&str] = &["jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff"];

pub fn is_previewable(extension: &str) -> bool {
    PREVIEWABLE.contains(&extension.to_lowercase().as_str())
}

/// Downscaled, Gaussian-blurred JPEG of an image, as upload-TX preview fields.
pub fn blurred_preview(bytes: &[u8]) -> Result<Value, String> {
    let img = image::load_from_memory(bytes).map_err(|e| format!("not a readable image: {e}"))?;
    let small = img.resize(MAX_W, MAX_H, FilterType::Triangle).to_rgb8();
    let blurred = image::imageops::blur(&small, BLUR_SIGMA);
    let mut out = Cursor::new(Vec::new());
    JpegEncoder::new_with_quality(&mut out, JPEG_QUALITY)
        .encode_image(&blurred)
        .map_err(|e| e.to_string())?;
    let data = out.into_inner();
    Ok(json!({
        "preview_data": STANDARD.encode(&data),
        "preview_hash": sha256_hex(&data),
        "preview_width": blurred.width(),
        "preview_height": blurred.height(),
        "blur": "blur",
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preview_is_small_blurred_jpeg() {
        let mut src = image::RgbImage::new(1200, 900);
        for (x, y, p) in src.enumerate_pixels_mut() {
            *p = if (x / 20 + y / 20) % 2 == 0 { image::Rgb([255, 255, 255]) } else { image::Rgb([0, 0, 0]) };
        }
        let mut png = Cursor::new(Vec::new());
        image::DynamicImage::ImageRgb8(src).write_to(&mut png, image::ImageFormat::Png).unwrap();
        let p = blurred_preview(png.get_ref()).unwrap();
        assert_eq!((p["preview_width"].as_u64(), p["preview_height"].as_u64()), (Some(480), Some(360)));
        let jpeg = STANDARD.decode(p["preview_data"].as_str().unwrap()).unwrap();
        assert_eq!(&jpeg[..2], &[0xFF, 0xD8]);
        let decoded = image::load_from_memory(&jpeg).unwrap().to_luma8();
        let (min, max) = decoded.pixels().fold((255u8, 0u8), |(lo, hi), p| (lo.min(p[0]), hi.max(p[0])));
        assert!(max - min < 160, "checkerboard edges should be smoothed, got {min}..{max}");
        assert!(blurred_preview(b"not an image").is_err());
    }
}
