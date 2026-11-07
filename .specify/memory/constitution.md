<!--
Báo cáo tác động đồng bộ — 2026-10-23.
Phiên bản 1.3.0 -> 1.4.0 theo yêu cầu trực tiếp của chủ dự án, là phê duyệt sửa đổi này.
Lý do: tuyệt đối không lưu ảnh gốc đầu vào trên R2; chỉ lưu output đã xử lý ở Python.
Giữ thiết kế 1.3.0: Python sở hữu findie_search/hybrid; .NET giữ nghiệp vụ; RabbitMQ lâu dài.
Mở rộng nguyên tắc II, IV, V: ảnh gốc chỉ ở bộ nhớ ứng dụng trong request có deadline,
transport ảnh tạm không durable/DLQ; retry ảnh đầu vào mất khi process mất RAM.
Tác động: đồng bộ đặc tả, kiến trúc, công nghệ, thiết kế DB và các bản tài liệu/sơ đồ phát hành.
DDL/ERD/từ điển 16 bảng/164 cột là snapshot bootstrap trước hybrid, không phải schema đích.
TODO migration: thay FK gốc bắt buộc bằng processed_object_id, object_kind processed và retention;
không diễn giải original_object_id thành output. Kiểm kê/dọn original cũ có kiểm soát nếu có.
Tiếp tục migration findie_search/ACL/FTS, vector không FK xuyên DB, outbox snapshot/tombstone
và document_version. ai_jobs.redact_image bootstrap không biểu diễn được luồng ảnh tạm mới.
TODO triển khai: queue ảnh non-durable/exclusive/auto-delete, nonpersistent/TTL/no body DLQ, chặn raw log/
backup; broker có thể page xuống đĩa, không tuyên bố bảo đảm chỉ RAM hoặc xóa forensic.
RabbitMQ.Client/aio-pika/psycopg 3 và cấu hình hybrid là đề xuất chưa cài/chưa đo.
Chỉ sửa tài liệu; không đổi SQL/runtime hoặc thực hiện di trú dữ liệu trong lần cập nhật này.
-->

# Hiến chương dự án Findie

## Các nguyên tắc cốt lõi

Findie kết nối người mất đồ, người đang giữ đồ và các điểm tiếp nhận. Hiến chương này quy định
các nguyên tắc cho sản phẩm khả dụng tối thiểu (MVP), dựa trên
[đặc tả Findie](../../docs/product/DAC_TA_FINDIE.md).
Kho dự án hiện chứa bản demo ý tưởng và tài liệu đặc tả, chưa có ứng dụng vận hành thực tế.
Các biện pháp bảo đảm dưới đây được xác lập là bắt buộc từ lần ban hành đầu tiên; điều đó
không có nghĩa chúng đã được triển khai. PHẢI (MUST) và KHÔNG ĐƯỢC (MUST NOT) biểu thị các
yêu cầu bắt buộc đối với công việc triển khai.

### I. Hoàn thiện hành trình tìm và nhận lại đồ cốt lõi

MVP PHẢI hỗ trợ đăng đồ nhặt được, tìm bằng mô tả tiếng Việt khi không có ảnh, tìm bằng ảnh
và hướng dẫn nhận lại theo người hoặc nơi đang giữ đồ. Hệ thống PHẢI phân biệt cá nhân giữ,
điểm tiếp nhận và nơi ngoài hệ thống. Yêu cầu nhận đồ do cá nhân giữ PHẢI cho phép từ 0 đến 3
câu hỏi xác minh; KHÔNG ĐƯỢC ngăn gửi yêu cầu chỉ vì không có câu hỏi. Hội thoại chỉ được mở
sau khi yêu cầu đã được phê duyệt. Nhận tại điểm tiếp nhận PHẢI có xác minh trực tiếp và
ghi nhận bàn giao. KHÔNG ĐƯỢC coi nơi ngoài hệ thống là điểm tiếp nhận đã đăng ký.

Thanh toán, phí nhận lại đồ, vận chuyển, tích hợp mạng xã hội, thông báo đẩy, bảng quản trị
đầy đủ và tự động kết luận quyền sở hữu nằm ngoài phạm vi MVP này. Mọi mở rộng phạm vi PHẢI
được giải trình trong đặc tả tính năng về đóng góp cho hành trình tìm và nhận lại đồ cốt lõi.

### II. Thực thi quyền truy cập và bảo vệ riêng tư tại backend

Backend .NET PHẢI xác thực các thao tác được bảo vệ và kiểm tra quyền đối với từng lần đọc,
thay đổi tài nguyên, kết nối hội thoại, lấy lịch sử và gửi tin nhắn, dựa trên trạng thái hiện
tại phía máy chủ. Chỉ các bên thuộc yêu cầu mới được truy cập hội thoại của mình; yêu cầu
đang chờ hoặc bị từ chối KHÔNG ĐƯỢC mở hội thoại. Nhân viên PHẢI chỉ thao tác tại điểm được
phân công, theo quyền do máy chủ quản lý. KHÔNG ĐƯỢC dùng việc ẩn nút trên React để thay thế
kiểm tra quyền.

Dữ liệu trả về công khai và đầu vào tìm kiếm KHÔNG ĐƯỢC chứa câu trả lời xác minh, tin nhắn
riêng hoặc địa chỉ nhà của cá nhân. Chỉ người gửi yêu cầu và người xét duyệt có quyền mới
được xem câu trả lời. Bằng chứng riêng tư KHÔNG ĐƯỢC đưa vào vector tìm kiếm công khai.
Ảnh gốc đầu vào, kể cả ảnh truy vấn, KHÔNG ĐƯỢC ghi vào R2, tệp tạm ứng dụng, DB/outbox,
nhật ký, DLQ hoặc backup. .NET PHẢI kiểm quyền/giới hạn byte và giữ upload trong bộ nhớ có
giới hạn; Python PHẢI giải mã, kiểm MIME/pixel, nhận diện vùng nhạy cảm và xử lý trước khi
có thể lưu bất kỳ object ảnh nào. Có vùng nhạy cảm PHẢI che/mờ; không có vùng nhạy cảm vẫn
PHẢI chuẩn hóa, loại EXIF và encode ảnh mới. Lỗi mô hình KHÔNG ĐƯỢC coi là không nhạy cảm;
không có output hợp lệ thì KHÔNG ĐƯỢC ghi R2. Không có API/download ảnh gốc. Byte đầu vào
chỉ ở RAM .NET/Python trong request, PHẢI được bỏ sau hoàn tất/lỗi/deadline; transport broker
tạm có giới hạn riêng và không tạo cam kết forensic chỉ RAM.
Thông tin bí mật PHẢI nằm ở phía máy chủ; nhật ký KHÔNG ĐƯỢC chứa thông tin đăng nhập, token
hoặc bằng chứng riêng tư. Kế hoạch triển khai PHẢI quy định giới hạn tần suất cho đăng tin,
gửi yêu cầu, tải tệp và nhắn tin.

### III. Ghi nhận nơi giữ thực tế trong một giao dịch toàn vẹn

Mỗi món đồ PHẢI có đúng một người hoặc nơi đang giữ và tối đa một lần hoàn tất trao trả.
Trạng thái yêu cầu nhận, trạng thái tiếp nhận, trạng thái món đồ và loại nơi giữ PHẢI được
phân biệt. Phê duyệt yêu cầu KHÔNG ĐƯỢC đồng nghĩa với đã trả đồ. Yêu cầu tiếp nhận đang chờ
hoặc bị từ chối KHÔNG ĐƯỢC làm thay đổi nơi giữ; chỉ xác nhận đã nhận đồ thực tế của nhân
viên được phân công mới cho phép chuyển nơi giữ sang điểm tiếp nhận.

Backend PHẢI kiểm tra lại quyền và trạng thái hiện tại tại thời điểm thay đổi dữ liệu.
Các thay đổi liên quan đến nơi giữ, trạng thái và lịch sử phục vụ kiểm tra PHẢI được lưu
trong cùng một giao dịch PostgreSQL. Cơ chế kiểm soát đồng thời và xử lý gửi lại PHẢI ngăn
thao tác nghiệp vụ trùng lặp, nơi giữ mâu thuẫn và lần hoàn tất trao trả thứ hai. Bản ghi bàn
giao PHẢI xác định người thực hiện, món đồ, thời điểm và thay đổi nơi giữ liên quan. Quy tắc
này giữ rõ sự khác biệt giữa dự định bàn giao và bàn giao đã diễn ra.

### IV. Giữ AI ở vai trò hỗ trợ, bảo đảm tương thích và khả năng khôi phục

Tìm kiếm PHẢI đưa ra các món đồ gợi ý, không kết luận quyền sở hữu hoặc công bố xác suất
người tìm là chủ sở hữu. Con người PHẢI xác minh trước khi trao trả. Vector văn bản và ảnh
chỉ được so sánh trong các không gian mô hình tương thích. Vector lưu trữ PHẢI kèm định
danh mô hình, phiên bản mô hình, số chiều và phiên bản nội dung nguồn; kết quả từ nội dung
cũ KHÔNG ĐƯỢC ghi đè vector biểu diễn nội dung mới hơn.

Python PHẢI tạo, kiểm tra, chuẩn hóa và lưu embedding vào database tìm kiếm riêng, đồng thời
thực hiện hybrid search. Baseline đề xuất kết hợp cosine pgvector với PostgreSQL full-text
search bằng weighted RRF; KHÔNG ĐƯỢC cộng điểm khác thang đo hoặc tự suy diễn từ khóa OCR
cho truy vấn chỉ có ảnh. Bảng cấu hình/mục tiêu độ chính xác theo trường hợp ở mục 5.3 của
[kiến trúc hệ thống](../../docs/architecture/system-architecture.md) là nguồn chuẩn để hiệu chỉnh và đo;
KHÔNG ĐƯỢC trình bày trọng số hoặc mục tiêu chưa đo như độ chính xác đã đạt.

Bài đăng hợp lệ PHẢI được giữ lại khi AI lỗi, kèm trạng thái lập chỉ mục rõ ràng và cơ chế
thử lại. KHÔNG ĐƯỢC giữ giao dịch cơ sở dữ liệu mở trong lúc mô hình suy luận. Tìm kiếm PHẢI
phân biệt không có kết quả với lỗi dịch vụ, đồng thời cung cấp bộ lọc cơ bản khi AI không
khả dụng. Việc mở rộng thời gian hoặc khu vực PHẢI được hiển thị cho người dùng. Chất lượng
tìm kiếm tiếng Việt và đối sánh ảnh PHẢI được đánh giá bằng dữ liệu có nhãn trước khi công
bố các khẳng định về chất lượng.

.NET PHẢI ghi job/outbox chứa snapshot công khai hoặc tombstone cùng giao dịch thay nguồn,
duyệt/thu hồi ảnh, nơi giữ, xuất bản/ẩn, trao trả hoặc xóa; phát lệnh sau commit qua RabbitMQ.
Phiên bản tài liệu từng món PHẢI tăng đơn điệu, kèm phiên bản/hash từng nguồn. Python PHẢI
ghi có điều kiện theo phiên bản và giữ watermark/tombstone để message cũ không phục hồi
nội dung đã gỡ. .NET PHẢI kiểm quyền, điều kiện hiển thị và phiên bản nguồn hiện tại trước
mỗi DTO kết quả và lượt đọc chi tiết; loại ứng viên cũ, chỉ lấy bù trong giới hạn hữu hạn.
Giao nhận có thể lặp; kết quả PHẢI giữ mã job, correlation, lease, phiên bản/hash nguồn và cấu hình mô
hình. Python PHẢI commit vector/bản chiếu tìm kiếm trước khi phát biên nhận thành công;
transaction này KHÔNG ĐƯỢC coi là nguyên tử với transaction hoàn tất job của .NET. .NET PHẢI
kiểm biên nhận trước khi commit trạng thái job, chỉ ACK sau commit hoặc sau khi chủ đích
loại kết quả trùng/lỗi thời. Python chỉ ACK lệnh sau khi kết quả được broker
xác nhận và định tuyến. Retry PHẢI hữu hạn, do .NET lưu số lần thử/lịch thử lại; message sai
schema hoặc poison vĩnh viễn của lệnh chỉ mục bền vững PHẢI vào DLQ có retention,
KHÔNG ĐƯỢC lặp requeue vô hạn. Ngoại lệ ảnh gốc: `image.redact` và message ảnh đầu vào
PHẢI là request/reply tạm, không ghi raw bytes trong durable job/outbox hoặc body DLQ.
Chỉ retry khi ảnh còn trong RAM và chưa hết deadline; crash/mất RAM PHẢI yêu cầu tải lại,
không hứa phát lại ảnh gốc từ job bền vững. Lỗi kết thúc chỉ giữ mã lỗi an toàn và drop body.

### V. Xây dựng hệ thống tối giản có thể kiểm chứng

MVP PHẢI bắt đầu với một giao diện React, một backend nghiệp vụ .NET, một Python AI worker,
RabbitMQ, một PostgreSQL instance với hai logical database `findie`/`findie_search` và kho
lưu tệp ảnh riêng. `findie` chỉ do .NET truy cập; `findie_search` chỉ do Python truy cập.
Không cần thêm sản phẩm hoặc máy chủ vector DB cho baseline. FastAPI chỉ phục vụ health
và vận hành nội bộ; lệnh/kết quả AI PHẢI đi qua RabbitMQ. Dịch vụ hoặc
thư viện bổ sung PHẢI giải quyết một nhu cầu hiện tại đã được ghi nhận. Tái sử dụng khả năng
sẵn có của nền tảng và cách tổ chức trong dự án trước khi thêm lớp trừu tượng hoặc hạ tầng.

Mọi thay đổi hành vi có logic đáng kể PHẢI kèm kiểm thử tự động tập trung hoặc bước tự kiểm
tra có thể thực thi. Các luồng bị ảnh hưởng về phân quyền, chuyển trạng thái, bàn giao đồng
thời, gửi lại an toàn và khôi phục khi AI lỗi PHẢI có kiểm thử tích hợp. Giao diện PHẢI dùng
được trên thiết bị di động và bằng bàn phím, với nhãn trường nhập, dấu hiệu tiêu điểm rõ,
thông báo lỗi dễ đọc và dữ liệu nhập được giữ lại khi có lỗi. Dữ liệu demo, hành vi chưa
triển khai và hiệu năng chưa đo PHẢI được ghi chú đúng thực trạng.

## Bộ công nghệ và ranh giới trách nhiệm

Các nền tảng đã chọn dưới đây được lấy từ đặc tả sản phẩm và yêu cầu sửa đổi của chủ dự án.
Công nghệ bổ trợ vẫn là phương án đề xuất cho đến khi kế hoạch tính năng ghi nhận việc
lựa chọn và các phiên bản tương thích.
[Tài liệu kiến trúc hệ thống](../../docs/architecture/system-architecture.md) cụ thể hóa thiết kế đề xuất,
không tự biến thư viện hoặc mô hình đang cân nhắc thành yêu cầu bắt buộc của hiến chương.

| Hạng mục | Nền tảng đã chọn | Phương án bổ trợ cần xác nhận khi lập kế hoạch |
| --- | --- | --- |
| Giao diện web | React | TypeScript và Vite |
| API nghiệp vụ | .NET | ASP.NET Core Web API; EF Core với Npgsql |
| Dịch vụ AI | Python AI worker; FastAPI cho health/vận hành | Qwen3-VL-Embedding-2B cho vector văn bản/ảnh; Qwen3-VL-4B-Instruct cho nhận diện/OCR/vùng nhạy cảm; OpenCV xử lý ảnh |
| Kết nối .NET–Python | RabbitMQ, AMQP 0-9-1 lâu dài | RabbitMQ.Client cho .NET, aio-pika cho Python; chưa cài đặt/chốt phiên bản |
| Dữ liệu nghiệp vụ | PostgreSQL, database `findie`; chỉ .NET | EF Core/Npgsql cho nghiệp vụ, job/outbox và metadata R2 |
| Vector và tìm kiếm | PostgreSQL + pgvector, database `findie_search`; chỉ Python | psycopg 3, vector cosine chính xác 2048 chiều, PostgreSQL FTS và weighted RRF; cấu hình cần đo |
| Nhắn tin | .NET quản lý và kiểm tra quyền | SignalR, với tin nhắn lưu bền vững trong PostgreSQL |
| Ảnh và chỉ đường | Cloudflare R2 riêng tư chỉ chứa ảnh output đã xử lý; PostgreSQL lưu tham chiếu output | AWS SDK for .NET qua S3 API; một processed object hiện hành mỗi ảnh; liên kết chỉ đường thông thường |

React PHẢI gọi qua .NET để thực hiện thao tác nghiệp vụ. .NET PHẢI quản lý quy tắc nghiệp vụ,
phân quyền, truy cập PostgreSQL, điều kiện xuất hiện trong tìm kiếm và lưu trữ tin nhắn bền
vững, quản lý job/outbox, đọc/ghi R2 và tạo DTO từ dữ liệu nghiệp vụ hiện tại. Python PHẢI thực hiện embedding,
nhận diện/OCR và toàn bộ xử lý ảnh: giải mã, kiểm MIME/pixel, chuẩn hóa, EXIF, resize, làm
mờ/che và encode; kiểm vector, lưu vector/bản chiếu công khai và thực hiện hybrid search
trong `findie_search`. .NET KHÔNG ĐƯỢC giải mã/biến đổi ảnh, tạo/ghi/truy vấn vector hoặc
xếp hạng hybrid. Python KHÔNG ĐƯỢC quản lý yêu
cầu nhận đồ, nơi giữ, quyền hội thoại hoặc truy cập trực tiếp DB nghiệp vụ/R2.
.NET chỉ gửi byte ảnh gốc từ bộ nhớ qua luồng RabbitMQ tạm để Python tạo output;
dữ liệu này KHÔNG ĐƯỢC ghi R2, log, durable outbox hoặc dùng làm vector công khai.
Chỉ mô tả công khai, ảnh an toàn đã được duyệt hoặc đầu vào truy vấn tạm được phép xử lý
mới được dùng để tạo vector. Qwen chỉ đề xuất vùng cần che; OpenCV áp dụng xử lý và con người
kiểm tra output trước khi công khai. Khi cần che thêm, chỉ xử lý lại output hiện có hoặc
yêu cầu tải lại ảnh gốc; không thể lấy lại hay bỏ mờ từ một original đã lưu. Khi xử lý hoặc
duyệt lỗi, KHÔNG ĐƯỢC trả ảnh gốc thay thế.

Lưu lượng công khai PHẢI dùng HTTPS. FastAPI, RabbitMQ và PostgreSQL KHÔNG ĐƯỢC truy cập trực
tiếp từ internet công khai. Mỗi service PHẢI giữ kết nối broker riêng lâu dài, tái sử dụng
channel publish/consume, có heartbeat và reconnect; KHÔNG ĐƯỢC gọi HTTP trực tiếp cho AI.
Broker PHẢI kiểm tra định danh, ACL theo exchange/queue và bảo vệ dữ liệu khi truyền.
Ảnh dùng body AMQP nhị phân, metadata JSON nhỏ trong header; không base64 hoặc URL tùy ý.
Giới hạn cơ sở đề xuất là 10 MiB cho mỗi body ảnh; văn bản/biên nhận/ứng viên dùng JSON,
vector được Python lưu trực tiếp tại database tìm kiếm. Broker không
là kho ảnh lâu dài nhưng vẫn có dữ liệu riêng tư trong message và có thể trên đĩa; PHẢI có
retention/TTL và giới hạn hàng đợi phù hợp. Queue ảnh `findie.ai.image` PHẢI non-durable,
auto-delete, message nonpersistent, TTL hữu hạn và không dead-letter raw body; cuối luồng
ACK/drop và chỉ giữ mã lỗi an toàn. Topology/owner cần chốt ở bootstrap. RabbitMQ vẫn có
thể page message nonpersistent xuống đĩa: TTL/logical delete không bảo đảm xóa forensic.
PHẢI chặn raw body log, DLQ và backup. Hợp đồng message PHẢI kiểm đầu vào, timeout
và lỗi rõ ràng. Thời điểm sự kiện hệ thống PHẢI được lưu theo
UTC và hiển thị theo `Asia/Ho_Chi_Minh`; ngày và khoảng giờ do người dùng ước lượng PHẢI
giữ nguyên tính không chắc chắn.

Bản demo ban đầu PHẢI dùng một bản chạy .NET. Kế hoạch dùng nhiều bản chạy PHẢI giải quyết
phân phối sự kiện hội thoại và xử lý tác vụ nền đồng thời trước khi mở rộng. Khi chốt phương
án triển khai, PHẢI kiểm tra phiên bản môi trường chạy, độ bền lưu trữ, giấy phép mô hình,
nhu cầu phần cứng và chi phí; hiến chương này không đưa ra cam kết tương thích hay mức dịch
vụ (SLA).

## Luồng kỹ thuật và quy trình phát triển

### Luồng kỹ thuật bắt buộc

1. **Đăng tin và lập chỉ mục:** React gửi dữ liệu và ảnh đến .NET; backend kiểm nghiệp vụ,
   quyền/giới hạn byte, giữ ảnh gốc trong RAM và gửi `image.redact` tạm qua RabbitMQ. Python
   kiểm tệp, nhận diện nhạy cảm, che/mờ nếu có và luôn chuẩn hóa/loại EXIF/encode output;
   lỗi hoặc không có output hợp lệ thì không ghi R2. .NET nhận output, kiểm hợp đồng/hash/
   số byte rồi mới dự trữ object loại `processed`, ghi output riêng tư vào R2 ngoài transaction.
   Sau upload thành công, .NET commit metadata/liên kết ảnh và snapshot/outbox nghiệp vụ.
   Ảnh chờ người có quyền duyệt, chưa vào manifest chỉ mục ảnh; chỉ output đã duyệt mới
   công khai và được Python lưu embedding vào `findie_search`. Byte gốc bị bỏ khi xong/lỗi/
   deadline; crash cần tải lại. Job/outbox chỉ mục từ output đã lưu có thể retry bền vững.
   Python commit vector/bản chiếu/FTS trước biên nhận; .NET commit trạng thái job riêng.
   Bài đăng/mô tả hợp lệ vẫn có thể được giữ và xem bằng danh sách cơ bản khi xử lý ảnh lỗi.
2. **Tìm kiếm:** React gửi mô tả tiếng Việt hoặc ảnh, kèm điều kiện khu vực và thời gian nếu
   có. .NET từ chối truy vấn rỗng, gửi `search.hybrid` bằng correlation/deadline hữu hạn qua
   RabbitMQ. Python tạo vector tạm và tìm trong `findie_search`, lọc trước khi lấy ứng viên,
   hợp nhất thứ hạng từ khóa/vector theo profile phù hợp, trả ID cùng phiên bản/nguồn/hạng.
   .NET kiểm quyền, bộ lọc, nguồn và tình trạng hiện tại, loại ứng viên cũ rồi tạo DTO giữ
   thứ tự hợp lệ; khi cần chỉ refill hữu hạn. Ảnh-only dùng vector và bộ lọc, không bịa nhánh
   từ khóa; kết hợp văn bản/ảnh PHẢI theo profile đã đánh giá. Khi tìm kiếm không khả dụng,
   .NET thông báo rõ và cung cấp danh sách/bộ lọc nghiệp vụ cơ bản.
3. **Yêu cầu nhận đồ và hội thoại:** Với đồ do cá nhân giữ, .NET lưu yêu cầu và câu trả lời
   nếu có. Người đang giữ có quyền phê duyệt hoặc từ chối. Chỉ phê duyệt mới cho phép mở
   hội thoại giữa các bên. Tin nhắn PHẢI được lưu bền vững trước khi xác nhận gửi thành công;
   ứng dụng phía người dùng PHẢI lấy lại lịch sử được phép xem sau khi kết nối lại.
   Phê duyệt không đồng nghĩa với hoàn tất trao trả.
4. **Chuyển vào điểm tiếp nhận:** .NET tạo yêu cầu chờ tiếp nhận và giữ nguyên nơi giữ hiện
   tại. Nhân viên được phân công xác nhận đã nhận thực tế; nơi giữ, trạng thái tiếp nhận và
   lịch sử được cập nhật trong một giao dịch toàn vẹn. Từ chối hoặc chỉ đồng ý trước về thủ
   tục không làm thay đổi nơi giữ.
5. **Trao trả:** Cá nhân đang giữ hoặc nhân viên điểm được phân công ghi nhận một lần bàn
   giao đã được xác minh và hoàn tất, thông qua chuyển trạng thái có kiểm tra quyền. Món đồ
   không còn xuất hiện trong kết quả tìm kiếm đồ có thể nhận. Nơi ngoài hệ thống chỉ cung
   cấp chỉ đường và hướng dẫn; mở chỉ đường KHÔNG ĐƯỢC đánh dấu đã trả. Quyền cập nhật việc
   trao trả tại nơi ngoài hệ thống phải được quy định rõ.

### Điều kiện lập kế hoạch và kiểm chứng

- Công việc PHẢI đi qua đặc tả tính năng, kế hoạch triển khai và danh sách nhiệm vụ theo thứ
  tự phụ thuộc. Mỗi kế hoạch PHẢI có bước kiểm tra tuân thủ hiến chương trước nghiên cứu
  và sau thiết kế.
- Đặc tả PHẢI phân biệt hành vi đã xác nhận, yêu cầu mới được thông qua, phương án đề xuất
  và quyết định còn chờ. Các quyết định liên quan bên dưới PHẢI được chốt trước khi triển
  khai tính năng chịu ảnh hưởng; quyết định không liên quan KHÔNG ĐƯỢC cản trở công việc độc lập.
- Rà soát PHẢI đối chiếu hành vi bị ảnh hưởng với BR01–BR06 và AC01–AC24 trong đặc tả khi
  phù hợp. Các kiểm tra bắt buộc gồm tìm chỉ bằng văn bản, ba nhánh nơi giữ, yêu cầu không
  có câu hỏi, truy cập API/hội thoại trực tiếp khi không có quyền, chờ tiếp nhận, trao trả
  đồng thời, gửi lại, vector lỗi thời và phương án dự phòng khi AI lỗi.
- Kiểm thử do hiến chương yêu cầu PHẢI được đưa vào đặc tả tính năng và danh sách nhiệm vụ,
  kể cả khi mẫu chung ghi kiểm thử là tùy chọn. Các mẫu không được sửa trong lần cập nhật này.
- Mỗi thay đổi PHẢI báo cáo các bước kiểm tra biên dịch, kiểu dữ liệu, kiểm thử và kiểm tra
  thủ công khả năng tiếp cận có liên quan, cùng giới hạn còn lại. Chất lượng và độ trễ tìm
  kiếm PHẢI được đo trên bộ dữ liệu và môi trường được nêu rõ; chưa mặc định mục tiêu định
  lượng cho đến khi kế hoạch tính năng xác định.
- Trước khi dùng dữ liệu người dùng thật, nhóm PHẢI xác định quy tắc lưu giữ và xóa dữ liệu,
  thực hành khôi phục bản sao lưu, kiểm tra quyền truy cập dữ liệu được bảo vệ và lịch sử
  thay đổi trạng thái.

### Các quyết định cần chốt trong kế hoạch tính năng

- **TODO(IDENTITY):** Đã chọn tạm thời chỉ Google OAuth và phiên cookie Identity ngày 24/10/2026;
  còn quyền xem khi chưa đăng nhập, thời hạn phiên và cách cấp quyền nhân viên.
- **TODO(RECOVERY_POLICY):** Quy định người tạo câu hỏi và việc bắt buộc trả lời, bằng chứng
  khi xác minh trực tiếp, duyệt nhiều yêu cầu, rút yêu cầu hoặc thu hồi phê duyệt, quyền hội
  thoại sau đổi nơi giữ hoặc hoàn tất trao trả, bước đồng ý trước tiếp nhận nếu có và người
  được cập nhật việc trao trả tại nơi ngoài hệ thống.
- **TODO(DATA_LIFECYCLE):** Quy định chỉnh sửa hoặc gỡ bỏ, lưu giữ và xóa ảnh, bằng chứng,
  hội thoại, kiểm duyệt và trách nhiệm xử lý tranh chấp trước khi dùng dữ liệu người dùng thật.
- **TODO(SEARCH_ACCEPTANCE):** Quy định độ rộng khu vực và thời gian, hành vi khi có cả hai
  đầu vào, dữ liệu đánh giá và mục tiêu đo được về chất lượng, độ trễ trước khi nghiệm thu AI.
- **TODO(IMPLEMENTATION_BASELINE):** Chốt phiên bản môi trường chạy, thư viện và mô hình,
  việc chọn công nghệ bổ trợ, cấu hình R2 và giới hạn tải lên/pixel, hạ tầng triển khai,
  phần cứng và ngân sách trong kế hoạch. Chốt hợp đồng RabbitMQ, giới hạn byte/header/queue,
  heartbeat/reconnect, timeout lease, publisher confirm/mandatory routing, ACK, backoff/DLQ,
  ACL/retention; kiểm thử message trùng, mất kết nối và crash giữa DB–broker. Tái dùng
  `ai_jobs` cho job/lease phù hợp; schema bootstrap chưa có outbox snapshot/tombstone hoặc
  đầy đủ loại lệnh đồng bộ/xóa. Trước triển khai PHẢI có migration tạo kho tìm kiếm và ACL,
  chuyển/tạo lại vector bỏ FK xuyên DB, FTS/GIN, outbox bền vững và ánh xạ `document_version`;
  kiểm thử chỉ mục trễ, đổi nguồn/duyệt, ẩn/xóa và kết quả cũ sau tombstone. Không đổi SQL
  hoặc triển khai migration trong lần cập nhật tài liệu này.
  Migration ảnh PHẢI bỏ FK original bắt buộc, dùng `processed_object_id`/kind `processed`,
  không lưu prefix original/temporary, tách xử lý ảnh tạm khỏi retry job bền vững; kiểm kê
  original cũ nếu có và lập kế hoạch dọn có kiểm soát, không xóa dữ liệu trong lần sửa này.

Đây là các quyết định được ghi rõ để xử lý sau, không phải chỗ trống chưa điền của mẫu hiến chương.

## Quản trị

Hiến chương này có hiệu lực ưu tiên so với mẫu chung, đề xuất kiến trúc và kế hoạch tính
năng riêng lẻ. Đặc tả sản phẩm cung cấp bối cảnh nghiệp vụ; mọi mâu thuẫn hoặc phạm vi mới
PHẢI được ghi nhận và giải quyết rõ ràng. Tài liệu kiến trúc PHẢI nhất quán với các nguyên
tắc này. Việc chọn công nghệ bổ trợ có thể được ghi trong kế hoạch mà không sửa hiến chương,
trừ khi làm thay đổi một yêu cầu của hiến chương.

Mọi sửa đổi PHẢI nêu lý do, nguyên tắc bị ảnh hưởng, tác động tương thích và công việc chuyển
đổi hoặc theo dõi cần thiết. Chủ dự án hoặc người phụ trách được chỉ định PHẢI phê duyệt
trước khi áp dụng. Rà soát đặc tả, kế hoạch và thay đổi PHẢI kiểm tra tuân thủ, đồng thời ghi
nhận ngoại lệ, lý do, người chịu trách nhiệm và mốc xử lý. Ngoại lệ KHÔNG ĐƯỢC âm thầm bỏ qua
kiểm soát truy cập, riêng tư hoặc tính toàn vẹn thông tin nơi giữ; yêu cầu mâu thuẫn cần có
sửa đổi hiến chương rõ ràng.

Phiên bản tuân theo quy tắc ngữ nghĩa: tăng MAJOR khi loại bỏ hoặc định nghĩa lại nguyên tắc
theo cách không tương thích; tăng MINOR khi thêm nguyên tắc hoặc mở rộng đáng kể hướng dẫn;
tăng PATCH khi làm rõ nội dung mà không đổi ý nghĩa. Ngày phê chuẩn ban đầu PHẢI được giữ
nguyên; sửa đổi PHẢI cập nhật ngày sửa đổi gần nhất. Phiên bản 1.0.0 được ban hành lần đầu,
thay thế mẫu chưa điền ngày 2026-10-21. Phiên bản 1.0.1 chuyển tài liệu sang tiếng Việt,
không thay đổi các quy tắc. Phiên bản 1.1.0 ghi nhận R2, phương án Qwen/OpenCV và cho phép
xử lý ảnh riêng tư nội bộ để tạo bản công khai an toàn theo yêu cầu chủ dự án. Đây là thay
đổi thiết kế tài liệu; chưa có dữ liệu hay ứng dụng vận hành cần di trú. Phiên bản 1.1.1
ghi nhận lựa chọn Instruct 4B theo yêu cầu chủ dự án ngày 2026-10-22.
Phiên bản 1.2.0 mở rộng ranh giới Python/.NET và bắt buộc kết nối RabbitMQ lâu dài theo yêu
cầu trực tiếp của chủ dự án ngày 2026-10-23; đây là phê duyệt áp dụng sửa đổi tài liệu.
Phiên bản 1.3.0 bổ sung Python sở hữu kho vector và hybrid search, tách hai logical database
và đồng bộ chỉ mục có kiểm soát theo yêu cầu trực tiếp của chủ dự án cùng ngày; yêu cầu này
là phê duyệt áp dụng sửa đổi. DDL bootstrap cần migration trước triển khai thiết kế mới.
Phiên bản 1.4.0 giới hạn R2 chỉ lưu output đã xử lý, loại lưu ảnh gốc và retry ảnh gốc bền
vững theo yêu cầu trực tiếp của chủ dự án ngày 2026-10-23, là phê duyệt áp dụng sửa đổi.
FK original và loại object trong DDL cũ không tương thích, phải migration trước triển khai.

**Phiên bản**: 1.4.0 | **Ngày phê chuẩn**: 2026-10-21 | **Sửa đổi gần nhất**: 2026-10-23
