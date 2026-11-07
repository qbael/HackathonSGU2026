export function validateImages(files: readonly Pick<File, "type" | "size">[]) {
  if (files.length > 3) throw new Error("Mỗi tin có tối đa 3 ảnh.");
  for (const file of files) {
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type))
      throw new Error("Chỉ nhận ảnh JPEG, PNG hoặc WebP.");
    if (!file.size || file.size > 10 * 1024 * 1024)
      throw new Error("Mỗi ảnh cần có dung lượng từ 1 byte đến 10 MB.");
  }
}

export function validatePostImages(files: readonly Pick<File, "type" | "size">[]) {
  if (!files.length) throw new Error("Tin nhặt được cần ít nhất 1 ảnh món đồ.");
  validateImages(files);
}

function validateDimensions(width: number, height: number) {
  if (!width || !height || Math.max(width, height) > 10000 || width * height > 40_000_000)
    throw new Error("Ảnh phải có mỗi cạnh tối đa 10000 px và không quá 40 triệu điểm ảnh.");
}

async function validateSource(file: File) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const view = new DataView(bytes.buffer);
  const tag = (offset: number) => String.fromCharCode(...bytes.subarray(offset, offset + 4));
  const uint24 = (offset: number) => bytes[offset] | bytes[offset + 1] << 8 | bytes[offset + 2] << 16;
  const invalid = () => new Error("Nội dung ảnh không hợp lệ hoặc không đúng định dạng đã chọn.");
  if (file.type === "image/jpeg") {
    if (bytes[0] !== 255 || bytes[1] !== 216 || bytes[2] !== 255) throw invalid();
    let offset = 2;
    while (offset < bytes.length) {
      if (bytes[offset++] !== 255) throw invalid();
      while (bytes[offset] === 255) offset++;
      const marker = bytes[offset++];
      if (marker === 0xda || marker === 0xd9) break;
      if (marker === 1 || marker >= 0xd0 && marker <= 0xd7) continue;
      if (offset + 2 > bytes.length) throw invalid();
      const length = view.getUint16(offset);
      if (length < 2 || offset + length > bytes.length) throw invalid();
      if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(marker)) {
        if (length < 8) throw invalid();
        validateDimensions(view.getUint16(offset + 5), view.getUint16(offset + 3));
        return;
      }
      offset += length;
    }
    throw invalid();
  }
  const png = file.type === "image/png";
  if (png
    ? ![137, 80, 78, 71, 13, 10, 26, 10].every((value, index) => bytes[index] === value)
    : tag(0) !== "RIFF" || tag(8) !== "WEBP") throw invalid();
  let width = 0, height = 0;
  let offset = png ? 8 : 12;
  while (offset < bytes.length) {
    if (offset + 8 > bytes.length) throw invalid();
    const kind = tag(offset + (png ? 4 : 0));
    const length = view.getUint32(offset + (png ? 0 : 4), !png);
    const end = offset + 8 + length + (png ? 4 : length % 2);
    if (end > bytes.length) throw invalid();
    if (png && offset === 8) {
      if (kind !== "IHDR" || length !== 13) throw invalid();
      width = view.getUint32(offset + 8);
      height = view.getUint32(offset + 12);
    } else if (!png && !width) {
      const start = offset + 8;
      if (kind === "VP8X" && length >= 10) {
        width = 1 + uint24(start + 4);
        height = 1 + uint24(start + 7);
      } else if (kind === "VP8 " && length >= 10) {
        width = view.getUint16(start + 6, true) & 0x3fff;
        height = view.getUint16(start + 8, true) & 0x3fff;
      } else if (kind === "VP8L" && length >= 5) {
        const size = view.getUint32(start + 1, true);
        width = 1 + (size & 0x3fff);
        height = 1 + ((size >>> 14) & 0x3fff);
      }
    }
    if (kind === "acTL" || kind === "ANIM" || kind === "ANMF"
      || kind === "VP8X" && length > 0 && (bytes[offset + 8] & 2))
      throw new Error("Chỉ nhận ảnh tĩnh; hãy chọn một ảnh JPEG, PNG hoặc WebP không có chuyển động.");
    offset = end;
  }
  validateDimensions(width, height);
}

async function resizeImage(file: File): Promise<Blob> {
  await validateSource(file);
  let image: ImageBitmap | null;
  try {
    image = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new Error("Không đọc được ảnh. Hãy chọn một ảnh JPEG, PNG hoặc WebP hợp lệ.");
  }
  try {
    validateDimensions(image.width, image.height);
    const scale = Math.min(1, 1600 / Math.max(image.width, image.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.width * scale));
    canvas.height = Math.max(1, Math.round(image.height * scale));
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Không thể xử lý ảnh trên trình duyệt này.");
    context.fillStyle = "white";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    image.close();
    image = null;
    const output = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((blob) => blob?.size ? resolve(blob)
        : reject(new Error("Không thể thu nhỏ ảnh. Hãy thử chọn lại ảnh.")), "image/jpeg", 0.92);
    });
    validateImages([output]);
    return scale === 1 && output.size >= file.size ? file : output;
  } finally {
    image?.close();
  }
}

const preparedImages = new WeakMap<File, Promise<Blob>>();

export function prepareImage(file: File): Promise<Blob> {
  validateImages([file]);
  let prepared = preparedImages.get(file);
  if (!prepared) {
    // Reuse the encoded bytes so retrying an upload keeps its idempotency hash.
    prepared = resizeImage(file).catch((error) => {
      preparedImages.delete(file);
      throw error;
    });
    preparedImages.set(file, prepared);
  }
  return prepared;
}
