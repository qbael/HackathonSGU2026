import { useEffect, useState } from "react";
import { Icon } from "./ui";

export function ImagePreviews({ files, onRemove }: {
  files: readonly File[];
  onRemove?: (index: number) => void;
}) {
  const [previews, setPreviews] = useState<string[]>([]);
  useEffect(() => {
    const urls = files.map((file) => URL.createObjectURL(file));
    setPreviews(urls);
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, [files]);
  if (!files.length) return null;
  return (
    <ul className="image-previews" aria-label="Ảnh đã chọn">
      {files.map((file, index) => (
        <li key={index}>
          <img src={previews[index]} alt={`Ảnh xem trước: ${file.name}`} />
          <span>{file.name}</span>
          {onRemove && (
            <button
              type="button"
              className="text-button"
              aria-label={`Xóa ảnh ${index + 1}: ${file.name}`}
              onClick={() => onRemove(index)}
            >
              <Icon name="close" size={16} />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
