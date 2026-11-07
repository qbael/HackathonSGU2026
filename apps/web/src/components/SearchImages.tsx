import { useId, useState } from "react";
import { validateSearchImages } from "../lib/search";
import { ImagePreviews } from "./ImagePreviews";
import { ErrorNotice, Icon } from "./ui";

export function SearchImages({ files, onChange }: {
  files: readonly File[];
  onChange: (files: File[]) => void;
}) {
  const hintId = useId();
  const [error, setError] = useState<Error | null>(null);
  return (
    <div className="search-images">
      <label className="upload-zone">
        <Icon name="upload" size={24} />
        <strong>Thêm ảnh để tìm kiếm ({files.length}/3)</strong>
        <span id={hintId}>JPEG, PNG, WebP · tối đa 3 ảnh, 10 MB/ảnh</span>
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          multiple
          disabled={files.length === 3}
          aria-describedby={hintId}
          onChange={(event) => {
            const selected = [...files, ...Array.from(event.target.files ?? [])];
            event.target.value = "";
            try {
              validateSearchImages(selected);
              onChange(selected);
              setError(null);
            } catch (cause) {
              setError(cause as Error);
            }
          }}
        />
      </label>
      <ImagePreviews files={files} onRemove={(index) => {
        onChange(files.filter((_, position) => position !== index));
        setError(null);
      }} />
      <p className="field-hint">Có thể dùng ảnh, mô tả hoặc cả hai. Ảnh chỉ dùng cho lượt tìm này.</p>
      <ErrorNotice error={error} />
    </div>
  );
}
