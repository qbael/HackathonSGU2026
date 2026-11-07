# Đánh giá mức sẵn sàng phát triển Findie MVP

**Ngày**: 2026-10-23 (Asia/Ho_Chi_Minh)
**Yêu cầu**: Kiểm tra các yêu cầu đã đủ để tiến hành phát triển ứng dụng chưa.
**Phạm vi**: Chất lượng yêu cầu toàn MVP; độ sâu tiêu chuẩn, ưu tiên quyền/riêng tư, vòng đời nghiệp vụ và tiêu chí nghiệm thu. Dành cho chủ dự án và reviewer trước lập kế hoạch, giao việc phát triển.
**Checklist**: Báo cáo ban đầu tham chiếu 34 tiêu chí yêu cầu tại `checklists/readiness.md`; tệp này hiện không có trong dự án. Đánh giá dưới đây không thay thế phê chuẩn chính sách sản phẩm.

## Kết luận

**Đủ căn cứ để tiếp tục nghiên cứu, lập kế hoạch và phát triển từng phần độc lập; chưa đủ để giao triển khai trọn MVP nghiệp vụ mà không tự quyết các chính sách còn mở.** Bộ khung đã có đặc tả/kế hoạch/nhiệm vụ riêng; chưa có bộ tương ứng cho các tính năng nghiệp vụ trong `docs/specs/`.

Không cần đợi chốt mọi quyết định để làm mọi việc. Hiến chương yêu cầu chốt quyết định trước tính năng chịu ảnh hưởng và không để quyết định không liên quan chặn công việc độc lập ([hiến chương, dòng 165–176](../../../.specify/memory/constitution.md#điều-kiện-lập-kế-hoạch-và-kiểm-chứng)).

## Những yêu cầu đã đủ rõ để làm cơ sở

- Phạm vi và phần ngoài MVP, danh mục F01–F11, các tác nhân cùng ba nhánh nơi giữ đã được ghi rõ ([đặc tả, dòng 15–65](../../product/DAC_TA_FINDIE.md#2-danh-mục-chức-năng)).
- BR01–BR06, một nơi giữ hiện tại, một lần hoàn tất trao trả và sự khác nhau giữa phê duyệt, tiếp nhận thực tế, trao trả đã rõ ([đặc tả, dòng 206–231](../../product/DAC_TA_FINDIE.md#7-quy-tắc-và-trạng-thái-nghiệp-vụ)).
- Dữ liệu công khai/riêng tư, quyền do backend kiểm soát và việc ảnh chưa duyệt không được công khai/lập chỉ mục ảnh đã có yêu cầu rõ ([đặc tả, dòng 257–265 và 309–327](../../product/DAC_TA_FINDIE.md#10-tìm-kiếm-thông-minh-và-yêu-cầu-chất-lượng)).
- Hành vi khi AI lỗi, gửi lại, thao tác đồng thời, kết nối lại hội thoại và kết quả AI lỗi thời đã được mô tả làm cơ sở thiết kế ([kiến trúc, dòng 181–194 và 212–249](../../architecture/system-architecture.md#6-yêu-cầu-nhận-đồ-hội-thoại-và-ba-nhánh-nhận-lại-đồ)).
- AC01–AC24 và NFR01–NFR06 cung cấp khung nghiệm thu nghiệp vụ; nhãn F/BR/AC giúp truy vết khi tách tính năng ([đặc tả, dòng 329–377](../../product/DAC_TA_FINDIE.md#11-tiêu-chí-nghiệm-thu)).

Các điểm trên hỗ trợ CHK001–CHK002, CHK012, CHK014, CHK018, CHK020–CHK021, CHK024–CHK025 và CHK027. Đây là nhận xét chất lượng tài liệu, không phải xác nhận đã triển khai hay kiểm thử thành công.

## Những quyết định phải chốt theo mốc

| Mức và thời điểm | Khoảng trống yêu cầu | Cần ghi thành quyết định cụ thể | Căn cứ và checklist |
| --- | --- | --- | --- |
| Trước tài khoản và các luồng được bảo vệ | Định danh, phiên và quyền chưa chốt | Nhà cung cấp/cách đăng nhập, quyền xem khi chưa đăng nhập, thời hạn phiên, người được cấp/thu hồi quyền nhân viên | Đặc tả §12, dòng 385; thiết kế dữ liệu dòng 43–45, 401; CHK003, CHK030 |
| Trước hoàn thiện đăng tin/công khai ảnh | Quyền duyệt ảnh và giới hạn đầu vào chưa được phê chuẩn | Ai được duyệt, có cho tự duyệt không, vùng nhạy cảm bắt buộc; số ảnh, byte/pixel, độ dài nội dung và chính sách lỗi đầu vào | Đặc tả dòng 87–95, 315; thiết kế dữ liệu dòng 159–162, 405; CHK005–CHK006 |
| Trước yêu cầu nhận đồ và hội thoại | Xác minh và vòng đời yêu cầu còn mở | Ai tạo câu hỏi, có bắt trả lời không; một món được duyệt bao nhiêu người; rút/thu hồi/đóng yêu cầu; xử lý yêu cầu cũ và quyền chat sau chuyển nơi giữ/trả đồ | Đặc tả dòng 154, 170, 386–387; thiết kế dữ liệu dòng 198–208, 235–239; CHK004, CHK008, CHK019, CHK023 |
| Trước hoàn thiện tiếp nhận/trao trả | Quy trình xác minh trực tiếp và quyền ở nơi ngoài hệ thống chưa chốt | Bằng chứng cần xuất trình, có dùng đồng ý trước tiếp nhận không, người được xác nhận trả đồ ở nơi ngoài hệ thống | Đặc tả dòng 188–202, 388; kiến trúc dòng 247–249; CHK004, CHK009 |
| Trước tìm kiếm nghiệp vụ; trước nghiệm thu AI | Bộ lọc chưa định lượng; chưa có ngưỡng đạt | Tính bắt buộc, phạm vi và cách mở rộng khu vực/thời gian; bộ dữ liệu có nhãn, chỉ số/ngưỡng tìm kiếm và bảo vệ ảnh; điều kiện đo độ trễ/quy mô | Đặc tả dòng 123–137, 338, 377, 390; kiến trúc dòng 186–194, 293–297; CHK007, CHK015–CHK017 |
| Trước triển khai từng tính năng qua Spec Kit | Chưa có bộ đặc tả/kế hoạch/nhiệm vụ nghiệp vụ và hợp đồng tương tác trong feature | Tách tính năng theo phụ thuộc; chốt đầu vào/đầu ra, quyền, lỗi/xung đột, gửi lại, phân trang; truy vết F/BR/AC và đưa kiểm chứng hiến chương vào nhiệm vụ | Bootstrap spec dòng 13–15; bootstrap tasks dòng 3–10; hiến chương dòng 165–176; CHK031–CHK032 |
| Trước dùng dữ liệu thật | Vòng đời dữ liệu và điều kiện vận hành chưa hoàn chỉnh | Sửa/gỡ bài, thời hạn lưu/xóa từng loại dữ liệu và backup, đầu mối tranh chấp; migration, DB role giới hạn quyền, khôi phục bản ghi/ảnh; giới hạn tần suất, retry và dọn tệp có số cụ thể | Đặc tả dòng 342, 389; kiến trúc dòng 260–261, 280–284; thiết kế dữ liệu dòng 274–275, 377–409; bootstrap plan dòng 19–21; CHK022–CHK023, CHK026, CHK028–CHK030 |

Các quyết định cần có người chịu trách nhiệm, người phê chuẩn và mốc gắn với tính năng; bảng nhóm quyết định hiện chưa phân công tên cụ thể (CHK033; đặc tả §12; kiến trúc §11). Mục Hồ sơ cũng cần chốt phạm vi tối thiểu hoặc loại trừ rõ khi lập đặc tả giao diện (CHK034; đặc tả dòng 61); đây không phải lý do chặn mọi phần độc lập.

Lưu ý về ảnh hưởng dữ liệu: thiết kế hiện nêu rút/thu hồi chưa được mô hình hóa thành trạng thái triển khai và khóa ngoại sẽ chặn đổi yêu cầu đã có hội thoại sang trạng thái khác. Chốt chính sách này có thể cần thay đổi lược đồ có chủ đích, không chỉ thêm nút giao diện ([thiết kế dữ liệu, dòng 235–239](../../database/database-design.md#hội-thoại-đúng-hai-bên)).

## Những điểm cần đồng bộ, không nên báo thiếu sai

- **Đã có baseline cho cả ảnh và mô tả**: người dùng chọn một chế độ, không tự trộn điểm (đặc tả dòng 125, 323; kiến trúc dòng 171–177). Mục quyết định còn mở ở đặc tả dòng 390 nên cập nhật trạng thái hoặc xác nhận baseline trong đặc tả tính năng; không cần phát minh thêm tính năng kết hợp điểm (CHK011).
- **Không cần chọn lại toàn bộ công nghệ**: kế hoạch bootstrap đã chốt runtime/gói local; cấu hình R2, hạ tầng suy luận và khả năng triển khai thực tế vẫn cần quyết định cho phần liên quan (bootstrap plan dòng 13–21; CHK030). Việc chưa benchmark không đồng nghĩa chưa có yêu cầu chức năng.
- **Trạng thái tài liệu cần phân lớp rõ hơn**: [Hướng dẫn phát triển](../../guides/development.md) và bootstrap ghi bộ khung đã có; một số tài liệu thiết kế vẫn mô tả trạng thái demo/chưa triển khai. Không dùng nhãn đó để kết luận bộ khung chưa tồn tại, cũng không dùng các nhiệm vụ bootstrap đã hoàn tất để kết luận F01–F11 đã xong (CHK013; bootstrap spec dòng 13–15).
- **Hiến chương ưu tiên**: các bất biến bắt buộc đã được hiến chương thông qua dù một số đoạn đặc tả còn ghi “đề xuất”. Khi viết đặc tả tính năng, ghi rõ yêu cầu bắt buộc kế thừa và quyết định sản phẩm thực sự còn mở (CHK010; hiến chương dòng 205–215).

## Trình tự để bắt đầu phát triển nghiệp vụ

1. Chốt định danh/quyền và chính sách duyệt ảnh trước nhóm tài khoản, đăng tin và ảnh riêng tư. Đồng thời chốt các giới hạn đầu vào cho nhóm này.
2. Viết đặc tả tính năng, kế hoạch và nhiệm vụ theo thứ tự phụ thuộc. Lấy F/BR/AC làm nguồn truy vết, ghi hợp đồng tương tác và các kiểm chứng bắt buộc vào nhiệm vụ; không kéo toàn bộ MVP vào tasks bootstrap.
3. Chốt quy tắc xác minh, yêu cầu, chat và bàn giao trước nhóm nhận đồ; chốt bộ lọc trước tìm kiếm. Có thể tiếp tục chuẩn bị dữ liệu tổng hợp, benchmark và công việc độc lập để xác định ngưỡng AI.
4. Hoàn tất chính sách lưu/xóa, giới hạn chống lạm dụng, migration, quyền runtime, sao lưu/khôi phục và cấu hình triển khai trước dữ liệu thật. Chốt ngưỡng đo được trước nghiệm thu AI; không đặt số tùy ý trong lần rà soát này.

## Phương pháp và giới hạn

- Đọc đặc tả sản phẩm, hiến chương, kiến trúc, thiết kế dữ liệu, README và toàn bộ spec/plan/tasks bootstrap. Hai lượt rà soát độc lập kiểm tra nghiệp vụ và sự nhất quán liên tài liệu. Không phát hiện mâu thuẫn nghiệp vụ trực tiếp làm vô hiệu các bất biến cốt lõi; vấn đề chính là các quyết định còn mở và thiếu phân rã tính năng nghiệp vụ.
- Script prerequisite ban đầu không xác định được feature vì chưa có `.specify/feature.json`. Chạy lại với đường dẫn tuyệt đối của feature duy nhất hiện có là `docs/specs/001-project-bootstrap`; script tự lưu con trỏ tương đối này. `AVAILABLE_DOCS` rỗng nghĩa là chưa có research/data-model/contracts/quickstart riêng trong feature, không có nghĩa tài liệu thiết kế trong `docs/` không tồn tại.
- Không có `.specify/extensions.yml` ở bước trước và sau tạo checklist; không có hook cần thực thi.
- Kết quả tạo mới gồm checklist và báo cáo này; không sửa đặc tả, hiến chương, kế hoạch, nhiệm vụ hoặc mã ứng dụng. Chỉ kiểm tra cấu trúc checklist, ID, dấu đánh giá và liên kết nội bộ của các tệp mới.
- Không chạy ứng dụng, build, kiểm thử thực thi, GPU, R2 hay kiểm chứng lại phiên bản công nghệ bên ngoài. Kết quả kiểm chứng cũ trong README chỉ là thông tin đã được ghi, không được coi là kết quả chạy lại hôm nay. Thư mục hiện không có Git metadata nên không có kiểm tra `git diff`.
- Rủi ro cần tránh: coi phương án đề xuất là chính sách đã được duyệt, hoặc coi task bootstrap hoàn tất là ứng dụng MVP đã sẵn sàng. Nhận xét này không phê chuẩn tự động các quyết định còn mở.
