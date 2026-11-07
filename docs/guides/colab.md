# Model Findie trên Google Colab

Notebook 01–03 là thử nghiệm độc lập, mở bằng **File → Upload notebook** tại [Google Colab](https://colab.research.google.com/).
Không cần clone project, chạy Docker hoặc cài model lên máy phát triển.

## Phiên chạy đầy đủ qua ngrok

[04_full_stack_ollama_ngrok.ipynb](../../notebooks/colab/04_full_stack_ollama_ngrok.ipynb) là notebook cho phiên local đầy đủ: `Qwen/Qwen3-VL-Embedding-2B` chạy bằng Transformers tạo embedding văn bản/ảnh 2048 chiều; `qwen3-vl:4b-instruct` chạy qua Ollama nhận diện vùng nhạy cảm. HTTPS ngrok chỉ expose gateway có Bearer token, không DB/broker. Cần ngrok account/authtoken, Colab GPU phù hợp và `FINDIE_OLLAMA_TOKEN` riêng. Chạy từng cell, tải JSON không chứa token rồi import bằng `python3 scripts/configure_ollama.py /path/findie-colab.json`; tiếp theo `make local-run`. Khi chuyển từ model cũ, chạy `make local-reindex` sau khi worker ready; không dùng lẫn vector của hai model.

Gateway giữ hợp đồng API Ollama để ứng dụng local dùng adapter hiện có, nhưng embedding Qwen được xử lý trực tiếp trong tiến trình Transformers. Model/processor và mã inference official được ghim như notebook 01; cấu hình embedding dùng SHA-256 của manifest revision/mã/profile/gói, không phải digest manifest Ollama.

Notebook 04 cài thư viện trước khi chạy Ollama/gateway. Nếu setup thay đổi phiên bản gói, chọn **Runtime → Restart session**, rồi chạy lại từ đầu; chạy lại cell trong cùng kernel sẽ bị chặn để tránh lỗi import như `GenerationMixin`. Cell nạp model kiểm import Transformers/Qwen trước khi tải trọng số và giữ traceback nguyên nhân gốc. Cảnh báo thiếu `HF_TOKEN` không chặn tải model Qwen công khai.

[Hướng dẫn đầy đủ](ai-service.md#model-trên-colab-qua-ngrok) mô tả cấp quyền Hub, doctor, ảnh output-only, đổi model/reindex và giới hạn Colab. Notebook 04 khác các notebook 01–03 dưới đây: có kết nối từ ứng dụng local trong phiên tương tác, không có keepalive hoặc hosting thường trực.

Cell mở gateway truyền authtoken qua cấu hình trong bộ nhớ và dùng domain mặc định do tài khoản ngrok cấp cho API endpoint v3. Chạy lại cell sẽ khởi động lại ngrok và đóng tunnel cũ; nếu URL đổi, tải/import lại JSON cấu hình ở local. Cách này tránh lỗi pyngrok `9.1.0` khi lệnh lưu token trả về `Authtoken already set`. Cell kiểm model/digest tại gateway loopback trước khi mở tunnel rồi kiểm HTTPS; lỗi từ ngrok hiển thị HTTP status và mã `ERR_NGROK_*`, không in body/credential. Chỉ mã endpoint chưa online `ERR_NGROK_3200` được kiểm lại tối đa 5 lần, mỗi lần cách 1 giây.

Cell cài Ollama trong notebook 03/04 tự cài `zstd` nếu thiếu trên Colab/Ubuntu; installer cần công cụ này để giải nén `.tar.zst`. Nếu bản notebook cũ báo `CalledProcessError` khi chạy `install.sh`, mở lại notebook đã cập nhật và chạy từ cell cấu hình. Bản cập nhật đưa tối đa 8000 ký tự cuối của log installer vào thông báo lỗi để chẩn đoán. Giữ lệnh `sh` trong cell: installer tự xử lý quyền quản trị; thêm `sudo sh` có thể làm mất biến môi trường `OLLAMA_VERSION`.

## Ollama cho dịch vụ tìm kiếm văn bản

[03_ollama_search.ipynb](../../notebooks/colab/03_ollama_search.ipynb) là notebook mới cho [Python AI service](ai-service.md). Mở trong runtime GPU sạch và chạy từng cell: cài Ollama `0.40.11` từ release có kiểm SHA-256, chạy loopback, pull `qwen3-embedding:4b`, so digest đã ghim với `/api/tags`, kiểm vector 2048 chiều hữu hạn/L2 rồi thử mô tả tiếng Việt. Mẫu cố tình có ví giống nhau tại phòng **E.205**, phòng **E.206**, **sảnh hội trường A** của Trường Đại học Sài Gòn. Sửa `QUERY` để quan sát kết quả.

Đổi model bằng `MODEL`, `EXPECTED_REVISION`, `DIMENSIONS` và instruction phù hợp. Khi digest không khớp, notebook in digest thực tế rồi dừng; cần xác minh trước khi đổi revision. Mẫu dùng cosine để kiểm embedding; service thực tế còn có từ khóa, tín hiệu vị trí và bộ lọc. Chưa có dữ liệu có nhãn để kết luận model hoặc số chiều nào tìm chính xác nhất.

`findie-ollama-sample.json` chỉ chứa cấu hình model không bí mật và kết quả query giả lập. Không xuất vector hoặc query tùy ý của người dùng, không nhập DB, không nhận credential. Đặt `DOWNLOAD_RESULTS=True` để tải JSON; mặc định tải qua bảng Files. Notebook chỉ nghe trên `127.0.0.1:11434`, không tạo tunnel công khai. Colab dành cho tính toán tương tác, không phải endpoint backend có uptime bảo đảm; xem [giới hạn Colab](https://research.google.com/colaboratory/faq.html) và [cách cấu hình endpoint phù hợp](ai-service.md#kết-nối-ollama-từ-xa-và-colab). Không thêm tác vụ tránh ngắt phiên. Sau thử nghiệm, chạy cleanup rồi **Disconnect and delete runtime**.

Kiểm cell Python, vector/ranking, chặn sai digest và nội dung export bằng CPU, không tải Ollama/model:

```sh
python3 -m unittest discover -s tests -p 'test_ollama_notebook.py'
```

Chưa chạy notebook 03 trên Colab GPU thật; `ollama ps` trong notebook cho biết model thực sự dùng CPU/GPU. Cấu hình Ollama dùng model text-only, tách biệt với hai thí nghiệm Qwen3-VL bên dưới.

## Hai thí nghiệm Qwen3-VL ban đầu

1. Mở [01_qwen_embedding.ipynb](../../notebooks/colab/01_qwen_embedding.ipynb), chọn **Runtime → Change runtime type → T4 GPU**. Chạy cell từ trên xuống: cài gói, kiểm GPU, tải model, thử mô tả tiếng Việt, thử ảnh, xuất ZIP, dọn GPU.
2. Tải kết quả bằng cách đặt `DOWNLOAD_RESULTS = True` và chạy lại cell xuất. Mặc định tệp nằm trong `/content`; xem/tải qua bảng Files của Colab cũng được.
3. **Disconnect and delete runtime**, mở [02_qwen_redaction.ipynb](../../notebooks/colab/02_qwen_redaction.ipynb) trong runtime GPU sạch. Chạy lần lượt, xem vùng model gợi ý, thêm `MANUAL_REGIONS` còn thiếu rồi chạy lại cell tạo bản nháp/xuất. Notebook giữ trạng thái `requires_human_review`; không tự duyệt công khai.

Notebook 01 tạo vector L2 2048 chiều, xếp hạng cosine riêng cho **văn bản → văn bản** và **ảnh → ảnh**. Hai chế độ không cộng điểm. Ảnh đồ vật tự vẽ chỉ dùng để kiểm luồng; chưa có bộ dữ liệu có nhãn để kết luận chất lượng tiếng Việt, ngưỡng cosine hoặc độ chính xác tìm kiếm.

Notebook 02 dùng `Qwen/Qwen3-VL-4B-Instruct`, NF4 4-bit, FP16 và SDPA để giảm bộ nhớ; giới hạn một ảnh, pixel và token. Vùng là `[x1,y1,x2,y2]` tương đối **0–1000**, áp lên ảnh đã sửa hướng/chuẩn hóa. OpenCV che kín chữ/số/mã; khuôn mặt mặc định che kín, có tùy chọn GaussianBlur. Kết quả rỗng cũng cần người xem lại toàn ảnh. Blur và phát hiện tự động không bảo đảm ẩn danh.

Chỉ dùng dữ liệu giả lập hoặc không nhạy cảm. Các cell tự tạo dữ liệu demo để chạy ngay; đặt `UPLOAD_IMAGE_QUERY` hoặc `UPLOAD_SYNTHETIC_IMAGE` thành `True` nếu muốn upload một ảnh demo khác. Tệp được kiểm bytes/định dạng/kích thước trước giải mã, tối đa 10 MiB, 20 megapixel, JPEG/PNG/WebP một frame; ảnh được sửa hướng EXIF, bỏ metadata và giới hạn cạnh dài 1024 px. Không dùng URL ảnh tùy ý. Không mount Drive, mở tunnel/FastAPI, nhận credential hoặc kết nối R2/DB thật. Output notebook có thể được lưu khi chia sẻ; xóa output trước khi chia sẻ và xóa runtime sau thử nghiệm.

GPU Free, thời lượng, quota và T4 không được Google bảo đảm. Cần ít nhất 7 GiB VRAM trống và PyTorch >= 2.8 có sẵn; notebook dừng nếu thiếu GPU hoặc môi trường không phù hợp. Chưa chạy inference/đo VRAM trên GPU thật. Nếu OOM, xóa runtime rồi chạy riêng một notebook; không tự rơi về CPU. Độ phân giải thấp và 4-bit có thể bỏ sót vùng/chữ nhỏ; phải đánh giá trước khi dùng vào sản phẩm.

## Phiên bản và kết quả

Các gói chính được ghim trong cell setup: Transformers 4.57.3, Accelerate 1.12.0, qwen-vl-utils 0.0.14, Hugging Face Hub 0.36.0, NumPy 2.2.6, Pillow 11.3.0; notebook 02 thêm bitsandbytes 0.48.2 và opencv-python-headless 4.12.0.88. Setup dùng constraint giữ nguyên phiên bản `torch`/`torchvision`/`torchaudio` có sẵn, không cài FlashAttention. Nếu Colab yêu cầu restart sau cài gói, restart session rồi chạy lại từ cell đầu. Môi trường Colab thay đổi theo thời gian; manifest ghi toàn bộ phiên bản thực tế và CUDA/GPU để đối chiếu.

| Thành phần | Revision bất biến |
| --- | --- |
| Qwen3-VL-Embedding-2B, processor và script official đi kèm | `9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda` |
| SHA-256 script embedding được kiểm trước khi import | `8ffa74a1a6bb759610c57865ea416fd4daf9936cb787520e1112a3e1d547f36a` |
| Qwen3-VL-4B-Instruct và processor | `ebb281ec70b05090aa6165b016eac8ec08e71b17` |

Embedding dùng class và EOS pooling trong mã official đã ghim. Tiền xử lý chạy trực tiếp và báo lỗi: wrapper official có nhánh thay ảnh lỗi bằng `NULL`, không phù hợp khi cần phân biệt inference ảnh lỗi. Không tải mã Python theo nhánh `main` vào runtime. Instruct dùng implementation của Transformers đã ghim, `trust_remote_code=False`.

`findie-embedding-results.zip` chứa vector, cosine ranking và manifest. `findie-redaction-draft.zip` chứa PNG nháp đã mã hóa lại, vùng JSON và manifest; không xuất ảnh gốc/overlay/raw response. Manifest ghi model/processor/code revision, prompt/profile, hash profile, phiên bản/hash nội dung nguồn, kích thước ảnh, môi trường chạy và trạng thái duyệt. Những tệp này dành cho kiểm tra thủ công; chưa có đường tự nhập DB hoặc tự đánh dấu ảnh an toàn. Backend vẫn phải kiểm revision/profile, source version và điều kiện duyệt trước khi dùng vào ứng dụng.

## Tự kiểm tra cục bộ, không tải model

Các notebook có assert kiểm ảnh/EXIF, vector, JSON và bounding box. Chạy lệnh sau từ thư mục gốc để kiểm cấu trúc notebook, biên dịch mọi code cell và chạy trực tiếp các hàm xử lý trong notebook bằng CPU:

```sh
uv run --no-project --python 3.12 \
  --with numpy==2.2.6 --with pillow==11.3.0 \
  --with opencv-python-headless==4.12.0.88 --with nbformat==5.10.4 \
  python notebooks/colab/test_notebooks.py
```

Kiểm tra này không cài Torch, không tải weights và không thay thế chạy các cell inference trên Colab GPU.

## Nguồn chính thức

- [Qwen3-VL-Embedding-2B model card](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B) và [script theo revision đã ghim](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B/blob/9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda/scripts/qwen3_vl_embedding.py).
- [Qwen3-VL-Embedding repository](https://github.com/QwenLM/Qwen3-VL-Embedding), [dependencies official tại commit được đối chiếu](https://github.com/QwenLM/Qwen3-VL-Embedding/blob/393e2978d27852b0d0230d6994f37f9c15bed73c/pyproject.toml).
- [Qwen3-VL-4B-Instruct model card](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct), [Qwen cookbook 2D grounding](https://github.com/QwenLM/Qwen3-VL/blob/main/cookbooks/2d_grounding.ipynb), [Transformers Qwen3-VL](https://huggingface.co/docs/transformers/v4.57.3/en/model_doc/qwen3_vl).
- [Transformers bitsandbytes/NF4](https://huggingface.co/docs/transformers/v4.57.3/en/quantization/bitsandbytes), [Google Colab FAQ và giới hạn Free](https://research.google.com/colaboratory/faq.html).
