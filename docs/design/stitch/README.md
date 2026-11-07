# Giao diện Findie từ Stitch

Nguồn: **Findie Lost and Found UI/UX**, project `4642962847276253252`.
Đã tải đủ 15 tệp HTML và 15 ảnh PNG bằng `curl -L`. Tên tệp là ID màn hình;
`manifest.json` giữ tên và URL nguồn để đối chiếu. Mã tham chiếu không được nạp vào ứng dụng.

| Màn hình nguồn | ID | Màn hình React |
| --- | --- | --- |
| Tổng hợp trải nghiệm và hệ thống giao diện | `6342057215db47af93af8256eb16e0c8` | Dùng làm tham chiếu chung |
| S01 — Trang bắt đầu | `dc6dcc03894442588a1d4c6017af9596` | `/` |
| S02 — Kết quả tìm kiếm | `3dab4e471dd84dbba6b1c781a4740d80` | `/search` |
| S03A — Cá nhân giữ | `148e4ec8b35a4f0ead4fe98517b9758c` | `/items/:id`, nhánh `person` |
| S03B — Findie Hub giữ | `45e350539d624a8cba742300c28734be` | `/items/:id`, nhánh `point` |
| S03C — Nơi ngoài hệ thống | `5cc234e9306447d6926e9ab48d2e7624` | `/items/:id`, nhánh `external` |
| S04 — Đăng nhập | `146c86f47e264daa87c89081102ca388` | `/signin` |
| S05 — Đăng tin ba bước | `b9761467cd1845ceab21a686fd37ed44` | `/post`, `/items/:id/edit` |
| S06 — Duyệt ảnh công khai | `81702f0b998b42d58dd016a2318c30a4` | `/items/:id/review` |
| S07 — Yêu cầu nhận đồ | `c4eff7c267174a8285fa7657d833aa39` | `/items/:id/claim` |
| S08 — Theo dõi yêu cầu | `3681c148976b42e58a55967fb60ae797` | `/requests`, `/claims/:id` |
| S09 — Người giữ xét duyệt | `17474d7a39b84f8f9f2b3b8ab4769750` | `/claims/:id`, theo quyền người dùng |
| S10 — Tin nhắn và bàn giao | `61d77a4a59f34cc89e0dd7a36243452e` | `/messages?conversation=:id` |
| S11 — Bài đăng của tôi | `47bd42ffef5c4e75b6acf086eaf949fd` | `/posts` |
| S12 — Chuyển đồ vào Hub | `cbae80ba11d949fd91849f293b308600` | `/items/:id/transfer`, `/hubs` |

## Phạm vi giao diện

- Dùng React, Tailwind/CSS và font Be Vietnam Pro đã có; không thêm dependency ứng dụng.
- Trang đầu cho phép nhập truy vấn. Các màn hình nghiệp vụ yêu cầu phiên Google theo chính sách API hiện tại; OAuth quay lại đúng màn hình đang thao tác.
- Tìm theo từ khóa, khu vực và ngày nhặt qua `GET /api/items` mặc định, có phân trang. Chọn gợi ý theo mô tả gọi `POST /api/search`, theo ảnh gọi `POST /api/search/image` với bytes ảnh và MIME; hiển thị thứ hạng, kết quả một phần và bộ lọc được mở rộng. Khi AI trả 503 có đường chuyển về bộ lọc cơ bản, không tạo điểm tương đồng giả.
- Đăng metadata trước; ảnh xử lý riêng, không làm mất tin khi xử lý ảnh lỗi. Chỉ bản ảnh đầu ra được hiển thị để duyệt. Tin vẫn có thể công khai bằng mô tả khi chưa có ảnh.
- CSRF cho các thao tác ghi, UUID idempotency cho các lệnh nghiệp vụ và UUID tin nhắn khi gửi lại. Dùng phiên bản hiện tại của món đồ/ảnh, hiển thị lỗi khi có xung đột.
- Câu hỏi xác minh và câu trả lời là tùy chọn. Chat chỉ mở sau khi duyệt yêu cầu; sau chuyển nơi giữ hoặc bàn giao, chat chỉ đọc. Lịch sử tin nhắn được cập nhật bằng nút tải lại và phân trang, chưa đẩy thời gian thực.
- Gửi đề nghị đến Hub không tự xác nhận đã nhận vật lý; nút hoàn tất trao trả yêu cầu xác nhận đối chiếu và bàn giao thực tế.
- `/profile` cập nhật tên hiển thị bằng `PUT /api/users/me`. `/intakes` và `/intakes/:id` theo dõi, lọc theo Hub, tiếp nhận/từ chối đề nghị; nhân viên dùng `itemRowVersion` trong response để xử lý được cả tin nháp/ẩn mà không mở quyền đọc món đồ.
- `/posts?scope=managed` lấy đồ đang quản lý, bao gồm đồ tại Hub. `/items/:id/return` xác nhận trao trả trực tiếp tại Hub/nơi ngoài hệ thống; Hub bắt buộc ghi chú xác minh. `/items/:id/history` hiển thị lịch sử bàn giao có phân trang. Backend kiểm quyền tiếp nhận/trao trả tương ứng của nhân viên; API chưa trả capability để ẩn từng nút theo quyền.

Đã bỏ bảng chọn prototype, chú thích thiết kế, đổi vai người dùng, OTP/eKYC giả lập,
điểm uy tín, số liệu cộng đồng, tỷ lệ AI khớp, khoảng cách/giờ mở cửa không có dữ liệu,
QR/phiếu hẹn giả, ảnh gốc, công cụ vẽ vùng che chưa được API hỗ trợ,
đính kèm chat, rút yêu cầu và xóa vĩnh viễn bài đăng. Tiếp nhận và trao trả tại Hub
dùng các API hiện có; chưa dựng dashboard hay công cụ quản trị nhân viên S13–S16.

## Kiểm tra

```sh
cd apps/web
npm test
npm run build
```

Khi triển khai, máy chủ web cần phục vụ `index.html` cho đường dẫn ứng dụng và chuyển
`/api` đến .NET. Các màn hình lấy dữ liệu từ API thật; không có dữ liệu mẫu tự xuất hiện
trong sản phẩm. AI/R2 và Google OAuth cần cấu hình máy chủ tương ứng.
