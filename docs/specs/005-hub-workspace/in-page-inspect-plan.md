# Kế hoạch điều chỉnh: Xóa bỏ mở Tab mới & Tích hợp Modal xem chi tiết tại chỗ trong Findie Hub

**Mã phân hệ**: `005-in-page-inspect` | **Trạng thái**: Bản kế hoạch triển khai | **Ngày tạo**: 2026-11-07  
**Mục tiêu**: Loại bỏ hoàn toàn việc mở tab trình duyệt mới (`target="_blank"`) ở cả 3 màn hình của Findie Hub Portal. Thay thế bằng các **Modal / Popup xem chi tiết trực tiếp tại chỗ** nhằm giữ vững không gian làm việc và tối ưu luồng thao tác của nhân viên trực trạm.

---

## 1. Danh sách 3 vị trí cần chuyển đổi

| Màn hình | Vị trí hiện tại (`target="_blank"`) | Trải nghiệm mới (In-page Modal) |
| :--- | :--- | :--- |
| **`HubInventory.tsx`** | Dòng 263-271: Nút "Xem chi tiết" mở `/items/{id}` ở tab mới | Mở **Modal Chi tiết Hiện vật** tại chỗ: xem ảnh đã che PII, mô tả, ngày giờ, nút "Trao trả đồ" ngay trong modal |
| **`HubIntakes.tsx`** | Dòng 252-258: Nút "Chi tiết món đồ" mở `/items/{id}` ở tab mới | Mở **Modal Kiểm tra Đơn tiếp nhận**: xem chi tiết đồ gửi vào trạm, nút "Duyệt vào kho" / "Từ chối" |
| **`HubHistory.tsx`** | Dòng 199-205: Nút "Lịch sử bàn giao" mở `/items/{id}/history` ở tab mới | Mở **Modal Lịch sử Luân chuyển**: tải và hiển thị dòng thời gian (`registered` $\rightarrow$ `received` $\rightarrow$ `returned`) tại chỗ |

---

## 2. Chi tiết kỹ thuật từng màn hình

### 2.1. Cải tiến `HubInventory.tsx` (Kho đồ tại trạm)

#### A. Khai báo State:
```tsx
// State lưu món đồ đang xem chi tiết
const [inspectItem, setInspectItem] = useState<Item | null>(null);
```

#### B. Thay đổi nút bấm xem chi tiết (Dòng 263-271):
Thay vì thẻ `<a href="..." target="_blank">`, đổi thành thẻ `<button>` mở modal:
```tsx
<button
  type="button"
  className="button button-secondary button-small"
  onClick={() => setInspectItem(item)}
  style={{ flex: 1, textAlign: "center" }}
>
  Xem chi tiết
</button>
```

#### C. Bổ sung Modal Chi tiết Hiện vật vào cuối Component:
```tsx
{inspectItem && (
  <div className="hub-modal-backdrop" onClick={() => setInspectItem(null)}>
    <div className="hub-modal" style={{ maxWidth: 700 }} onClick={(e) => e.stopPropagation()}>
      <div className="hub-modal-header">
        <h3>Chi tiết hiện vật lưu kho</h3>
        <button type="button" className="text-button" onClick={() => setInspectItem(null)}>
          <Icon name="close" size={20} />
        </button>
      </div>

      <div className="hub-modal-body">
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", alignItems: "center" }}>
          <Badge value={inspectItem.lifecycle} />
          <span style={{ fontSize: "0.8125rem", color: "#64748b", marginLeft: "auto" }}>
            Mã đồ: #{inspectItem.id.slice(0, 8)}
          </span>
        </div>

        <h2 style={{ fontSize: "1.25rem", fontWeight: 700, margin: "0 0 0.5rem", color: "#0f172a" }}>
          {inspectItem.title}
        </h2>

        <div style={{ marginBottom: "1.25rem" }}>
          <h4 style={{ fontSize: "0.875rem", fontWeight: 600, color: "#475569", margin: "0 0 0.25rem" }}>
            Mô tả công khai
          </h4>
          <p style={{ background: "#f8fafc", padding: "0.75rem", borderRadius: 8, fontSize: "0.875rem", margin: 0, whiteSpace: "pre-wrap" }}>
            {inspectItem.publicDescription}
          </p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem", marginBottom: "1.25rem", fontSize: "0.875rem" }}>
          <div>
            <span style={{ color: "#64748b" }}>Khu vực nhặt:</span> <strong>{inspectItem.foundArea}</strong>
          </div>
          <div>
            <span style={{ color: "#64748b" }}>Ngày tạo bài:</span> <strong>{formatDate(inspectItem.createdAt, true)}</strong>
          </div>
        </div>

        {inspectItem.images && inspectItem.images.length > 0 && (
          <div>
            <h4 style={{ fontSize: "0.875rem", fontWeight: 600, color: "#475569", margin: "0 0 0.5rem" }}>
              Hình ảnh hiện vật ({inspectItem.images.length})
            </h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "0.75rem" }}>
              {inspectItem.images.map((img) => (
                <div key={img.id} style={{ borderRadius: 8, overflow: "hidden", border: "1px solid #e2e8f0", background: "#f1f5f9" }}>
                  <img src={img.previewUrl} alt="" style={{ width: "100%", height: 110, objectFit: "cover" }} />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="hub-modal-footer">
        <button type="button" className="button button-outline" onClick={() => setInspectItem(null)}>
          Đóng
        </button>
        {inspectItem.lifecycle !== "returned" && (
          <button
            type="button"
            className="button"
            onClick={() => {
              const target = inspectItem;
              setInspectItem(null);
              handleOpenReturnModal(target);
            }}
          >
            <Icon name="check" size={16} />
            <span>Tiến hành trao trả cho chủ</span>
          </button>
        )}
      </div>
    </div>
  </div>
)}
```

---

### 2.2. Cải tiến `HubIntakes.tsx` (Bàn tiếp nhận)

#### A. Khai báo State:
```tsx
// State lưu đề nghị cần xem chi tiết món đồ
const [previewIntakeItem, setPreviewIntakeItem] = useState<{ intake: Intake; item: Item } | null>(null);
const [loadingPreviewId, setLoadingPreviewId] = useState<string | null>(null);
```

#### B. Hàm xem chi tiết đồ:
```tsx
const handleViewIntakeDetail = async (intake: Intake) => {
  setLoadingPreviewId(intake.id);
  try {
    const item = await api<Item>(`/api/items/${intake.itemId}`);
    setPreviewIntakeItem({ intake, item });
  } catch (err) {
    alert(err instanceof Error ? err.message : "Không thể tải thông tin món đồ.");
  } finally {
    setLoadingPreviewId(null);
  }
};
```

#### C. Thay đổi nút bấm (Dòng 252-258):
```tsx
<button
  type="button"
  className="button button-secondary button-small"
  onClick={() => handleViewIntakeDetail(intake)}
  disabled={loadingPreviewId === intake.id}
>
  {loadingPreviewId === intake.id ? "Đang tải…" : "Chi tiết món đồ"}
</button>
```

#### D. Bổ sung Modal Chi tiết Đề nghị tiếp nhận:
Tương tự cấu trúc modal của `HubInventory`, hiển thị ảnh, thông tin đồ và 2 nút hành động:
- **"Tiếp nhận vào Hub"**: Gọi hàm `handleOpenActionModal("receive", previewIntakeItem.intake)`.
- **"Từ chối"**: Gọi hàm `handleOpenActionModal("reject", previewIntakeItem.intake)`.

---

### 2.3. Cải tiến `HubHistory.tsx` (Nhật ký luân chuyển)

#### A. Khai báo State:
```tsx
const [timelineEvents, setTimelineEvents] = useState<{ itemId: string; events: CustodyEvent[] } | null>(null);
const [loadingTimelineId, setLoadingTimelineId] = useState<string | null>(null);
```

#### B. Hàm tải dòng thời gian bàn giao:
```tsx
const handleViewCustodyHistory = async (itemId: string) => {
  setLoadingTimelineId(itemId);
  try {
    const res = await api<Page<CustodyEvent>>(`/api/items/${itemId}/custody-events?page=1&pageSize=20`);
    setTimelineEvents({ itemId, events: res.items });
  } catch (err) {
    alert(err instanceof Error ? err.message : "Không thể tải lịch sử bàn giao.");
  } finally {
    setLoadingTimelineId(null);
  }
};
```

#### C. Thay đổi nút bấm (Dòng 199-205):
```tsx
<button
  type="button"
  className="button button-secondary button-small"
  onClick={() => handleViewCustodyHistory(entry.itemId)}
  disabled={loadingTimelineId === entry.itemId}
>
  {loadingTimelineId === entry.itemId ? "Đang tải…" : "Lịch sử bàn giao"}
</button>
```

#### D. Bổ sung Modal Dòng thời gian Lưu chuyển:
Hiển thị danh sách các sự kiện bất biến (`registered`: Đăng ký giữ đồ, `received`: Hub tiếp nhận, `returned`: Đã trao trả cho chủ sở hữu) với thời gian và số lần lưu ký (`custodyVersion`).

---

## 3. Kịch bản kiểm thử (Verification Checklist)

Sau khi hoàn tất chỉnh sửa:
1. **Kiểm tra `HubInventory`**:
   - Nhấp vào nút "Xem chi tiết" của bất kỳ món đồ nào $\rightarrow$ Modal hiển thị ngay trên trang hiện tại, KHÔNG mở tab mới.
   - Nhấp nút "Tiến hành trao trả" trong modal $\rightarrow$ Chuyển mượt mà sang form trao trả.
2. **Kiểm tra `HubIntakes`**:
   - Nhấp vào nút "Chi tiết món đồ" $\rightarrow$ Modal hiển thị thông tin và ảnh của đồ thất lạc, có thể bấm duyệt/từ chối ngay.
3. **Kiểm tra `HubHistory`**:
   - Nhấp vào nút "Lịch sử bàn giao" $\rightarrow$ Modal hiển thị timeline các sự kiện custody của món đồ mà không bật tab mới.
4. **Kiểm tra mã nguồn**:
   - Quét lại toàn bộ thư mục `apps/web/src/pages/hub/` để đảm bảo không còn bất kỳ thuộc tính `target="_blank"` nào.
