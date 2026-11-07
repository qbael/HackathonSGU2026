# Đánh giá và lọc kết quả tìm kiếm

Python lấy tối đa **20 ứng viên duy nhất**, chấm và lọc toàn bộ pool rồi mới trả
cho .NET. .NET kiểm lại nguồn/trạng thái, áp dụng ưu tiên khu vực và bonus thời gian,
sau đó lấy tối đa 10 món. Không thêm kết quả yếu để đủ 10.

## Luồng chạy thật

1. Semantic/FTS/vị trí lấy pool 20, dùng RRF hợp nhất thứ hạng. Cosine được đo cho cả
   món từ khóa nằm ngoài semantic top 20, không dùng điểm thiếu như điểm thấp.
2. Có khu vực: chỉ mở rộng nếu không có món nào đạt cosine ảnh **hoặc** mô tả.
   Món local yếu không chiếm chỗ của kết quả ngoài khu vực.
3. Khi có cấu hình reranker, Python gửi `search.materials` qua RabbitMQ. .NET cấp
   mô tả công khai và một ảnh đã xử lý, đã duyệt cho mỗi ứng viên, kiểm nguồn trước
   và sau khi đọc storage. Consumer riêng không chặn request tìm kiếm đang chờ.
4. Python kiểm bytes/hash/MIME/phiên bản, tạo ảnh JPEG tối đa 512px trong RAM rồi
   gọi Qwen3-VL-Reranker-2B trên gateway hiện tại. Không đưa quyền R2 sang Python.
   Điểm ảnh là điểm tốt nhất qua tối đa ba ảnh query; mô tả được chấm riêng.
5. Một loại đạt ngưỡng là đủ. Điểm liên quan là điểm cao nhất trong các loại đạt.
   Loại các điểm dưới tỷ lệ so với món tốt nhất trong cùng khu vực/nhóm bằng chứng.
   Nhóm gồm cả hai loại đạt, chỉ ảnh đạt, chỉ mô tả đạt.

Toàn bộ bước lấy dữ liệu và chấm có **15 giây**, không phải 15 giây mỗi món.
Lỗi, quá giờ hoặc batch chưa đủ thì bỏ toàn bộ điểm model và lọc cosine trên pool;
những món đã được báo stale vẫn bị loại. HTTP trả `rankingMethod` là `reranker`
hoặc `similarity_fallback`; giao diện báo khi dùng dự phòng. Bonus thời gian không
cứu món dưới ngưỡng. RRF, cosine và relevance không phải xác suất sở hữu.

## Cấu hình và triển khai

| Cấu hình | Mặc định |
| --- | --- |
| `AI_RERANKER_MODEL` | `Qwen/Qwen3-VL-Reranker-2B` |
| `AI_RERANKER_REVISION` | Rỗng: chỉ lọc similarity; cấu hình fingerprint export từ notebook để bật model |
| `AI_RERANK_MIN_IMAGE_SCORE`, `AI_RERANK_MIN_TEXT_SCORE` | `0.5` |
| `AI_SEARCH_MIN_IMAGE_SIMILARITY`, `AI_SEARCH_MIN_TEXT_SIMILARITY` | `0.6`, dùng khi dự phòng và quyết định mở rộng khu vực |
| `AI_SEARCH_RELATIVE_SCORE_RATIO` | `0.75` |

Các ngưỡng là baseline chưa hiệu chỉnh, không phải kết quả benchmark. Ví dụ cùng
nhóm có điểm `0.92, 0.89, 0.86, 0.52` sẽ giữ ba món đầu với tỷ lệ `0.75`.

Notebook 04 nạp model tùy chọn trên GPU, ghim model/processor và profile FP16/SDPA.
Thiếu VRAM hoặc warmup lỗi không tắt embedding/redaction. `/v1/status` báo
`searchQuality.rerankerConfigured`, không khẳng định model đủ nhanh chỉ vì đã cấu hình.

Broker cần cập nhật ACL cho `findie.api.materials` và `findie.ai.materials.results`
theo [hợp đồng AMQP](../api/amqp.md). Queue tạm không có DLX, có TTL/giới hạn byte;
reply queue dùng `reject-publish` để lỗi rõ ràng thay vì mất chunk âm thầm.
Khởi động lại API/worker cùng phiên bản để dùng pool 20 và TTL mới. Không cần
migration database hoặc tạo lại embedding. Cấp cấu hình qua môi trường triển khai;
không đưa token/credential vào notebook export, dataset, log hoặc báo cáo.

## Dataset có nhãn

File JSON là mảng case. Ví dụ dưới đây là cấu trúc; thay UUID bằng món thực sự đã
lập chỉ mục trong corpus đánh giá, rồi người đánh giá xác nhận nhãn:

```json
[
  {
    "caseId": "wallet-text-positive",
    "split": "calibration",
    "mode": "text",
    "text": "Ví đen có khóa kéo vàng",
    "relevantItemIds": ["00000000-0000-0000-0000-000000000001"]
  },
  {
    "caseId": "unavailable-object",
    "split": "test",
    "mode": "text",
    "text": "Đàn piano màu tím",
    "relevantItemIds": []
  }
]
```

`mode` là `text`, `image` hoặc `combined`. Ảnh dùng trường `images` gồm 1–3 đường
dẫn tương đối trong thư mục dataset, chỉ nhận PNG/JPEG/WebP tổng hợp hoặc output
đã xử lý được phép. Không ghi ảnh gốc người dùng để tạo benchmark. `area`, `from`,
`until` tùy chọn. Tách calibration/test theo món đồ; loader từ chối nhãn món trùng
giữa hai phần. Không để ảnh gần trùng của một món xuất hiện ở cả hai phần.

Bổ sung đồ gần giống, khác góc/chữ trên ảnh, có/không dấu, chỉ một modality khớp,
khu vực/ngày và truy vấn không có đáp án. Không dùng UUID chưa được lập chỉ mục
để tuyên bố recall. Hiện chưa có bộ nhãn thật được commit hoặc kết quả GPU thực.

## Chạy evaluate

Chạy từ repo với cấu hình đã được cấp qua môi trường. Baseline text so sánh
semantic/lexical/hybrid trước lọc:

```sh
PYTHONPATH=services/ai services/ai/.venv/bin/python -m findie_ai.evaluate /path/to/cases.json
```

Đo đúng đường production Python, gồm cấp ảnh qua RabbitMQ, reranker và fallback:

```sh
PYTHONPATH=services/ai services/ai/.venv/bin/python -m findie_ai.evaluate /path/to/cases.json --production
```

Production cần API và worker đang chạy. `AI_EVALUATION_RABBITMQ_URL` là tài khoản
đánh giá riêng có quyền publish query và khai báo/consume reply queue tạm;
runtime AI không được mở rộng quyền để chạy CLI này. Không in URL broker có mật khẩu.

Báo cáo gồm Hit@10, MRR@10, `candidateRecallAt20` cho baseline, precision/recall
trên số kết quả thực trả, tỷ lệ bỏ trống query có đáp án, tỷ lệ gợi ý sai trên
query không có đáp án, số món trung bình, p50/p95 và tỷ lệ fallback theo mode/split.
Production không công bố recall pool thô khi không nhận pool chưa lọc từ worker.
Phạm vi là **trước eligibility và bonus .NET**; kiểm thử tích hợp kiểm phần .NET.

Hiệu chỉnh ngưỡng trên calibration rồi giữ cố định khi đo test. So sánh chất lượng
lọc và tỷ lệ fallback, không chỉ Hit@10; giảm trả sai mà mất nhiều món đúng cũng
là suy giảm. Chưa có benchmark đủ để bảo đảm VL 2B chấm 20 món trong 15 giây.
