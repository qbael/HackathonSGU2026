# API món đồ, yêu cầu, hội thoại và bàn giao

Cập nhật 30/10/2026. Base URL local: `http://127.0.0.1:5080`.
Đọc cùng [xác thực Google/cookie](README.md), [ảnh và tìm kiếm](media-search.md),
[hợp đồng AMQP](amqp.md), [đặc tả và quyết định](../specs/002-recovery-api/spec.md).

## Quy ước chung

- Tất cả endpoint dưới đây yêu cầu cookie phiên Google còn hiệu lực. Chưa đăng nhập:
  **401**; tài khoản disabled: **403**, kể cả cookie được cấp trước đó.
- Ghi dữ liệu: lấy `GET /api/auth/csrf`, gửi token trong `X-CSRF-TOKEN` cùng cookie.
  Các thao tác tạo/sửa/xóa/xét duyệt/trao trả yêu cầu thêm `Idempotency-Key: <UUID khác 0>`.
  Tin nhắn dùng `clientMessageId` thay header này. Tìm kiếm chỉ yêu cầu CSRF.
- Khóa được giới hạn theo tài khoản; cùng khóa/thao tác/payload trả lại cùng tài nguyên,
  cùng mã nhưng khác payload/thao tác trả **409**. Rollback không ghi khóa thành công.
  Retry kiểm quyền đọc hiện tại; response biểu diễn tài nguyên hiện tại, không phải bản
  JSON đóng băng. Không tự hết hạn khóa nghiệp vụ.
- `Content-Type: application/json`, thuộc tính camelCase, UUID, thời điểm ISO 8601 UTC,
  ngày `yyyy-MM-dd`. Kestrel giới hạn JSON body 64 KiB. Client không được gán actor,
  người giữ, trạng thái, version nội bộ.
- Lỗi nghiệp vụ/validation dùng ProblemDetails (`title`, `status`, `traceId`; validation
  có `errors`). **400** đầu vào/CSRF/key sai; **403** thiếu quyền; **404** không có hoặc
  không được đọc tài nguyên riêng tư; **409** trạng thái/phiên bản/gửi lại xung đột;
  **429** vượt 120 request/phút/tài khoản. Khóa UUID sai trong path trả 404.
- Danh sách phân trang: `page=1..10000`, `pageSize=1..100`, mặc định 1/20;
  `{ "items": [], "page": 1, "pageSize": 20, "hasMore": false }`.
  Sắp xếp theo ngày tạo giảm dần rồi UUID; lịch sử custody theo version tăng dần.

Ví dụ header cho các lệnh `curl` bên dưới (cookie jar phải thuộc chính phiên của bạn):

```sh
curl -b cookies.txt http://127.0.0.1:5080/api/auth/csrf
curl -b cookies.txt -H 'X-CSRF-TOKEN: <token>' -H 'Idempotency-Key: <uuid>' \
  -H 'Content-Type: application/json' -d '<json>' http://127.0.0.1:5080/api/items
```

## Các kiểu dữ liệu

`ItemInput` được dùng khi tạo và PUT nội dung:

```json
{
  "title": "Ví màu đen",
  "publicDescription": "Ví đen có khóa kéo vàng; không công khai chi tiết xác minh.",
  "foundArea": "Công viên Bờ Sông",
  "foundTimePrecision": "date",
  "foundOn": "2026-10-13",
  "foundFrom": null,
  "foundUntil": null,
  "foundTimezone": "Asia/Ho_Chi_Minh",
  "verificationQuestions": ["Có đặc điểm riêng nào ở bên trong?"]
}
```

`title` 1–200, `publicDescription` 1–5000, `foundArea` 1–200 ký tự sau trim.
Câu hỏi 0–3, mỗi câu 1–500; không bắt buộc có câu hỏi hoặc câu trả lời. PUT thiếu
`verificationQuestions` nghĩa là thay bằng bộ rỗng. Claim cũ giữ nguyên snapshot.

Thời gian: `unknown` không có ngày/giờ; `date` chỉ có `foundOn`; `exact` chỉ có
`foundFrom`; `range` có `foundFrom <= foundUntil`, không có `foundOn`. Không chấp nhận
ngày hoặc thời điểm tương lai. Timestamp có offset được đổi UTC; timezone IANA giữ
ngữ cảnh ngày (mặc định Asia/Ho_Chi_Minh). Không tự bịa giờ khi chỉ biết ngày.

`ItemResponse` gồm `id`, `title`, `publicDescription`, `foundArea`, các trường thời gian,
`custody`, `lifecycle` (`active|returned`), `publicationState` (`draft|published|hidden`),
`rowVersion`, `documentVersion`, `createdAt`, `images`, `canClaim`, `canDelete`. `canClaim` phụ thuộc
người đang xem: chỉ true khi món published/active do cá nhân giữ và người xem không phải
người đăng hoặc người giữ hiện tại. `images` chỉ chứa output được
duyệt: `{id,position,contentVersion,url}`. `canDelete` cho biết người xem có quyền quản lý
hiện tại để xóa bài đăng, kể cả khi món đã trao trả. Không có email, bằng chứng hoặc object key R2.

`custody` gồm `kind`, `displayName` (cá nhân), `pointId`, `name`, `publicAddress`,
`instructions`; trường không áp dụng là null. Không có địa chỉ nhà người giữ.

## GET /api/items — danh sách và bộ lọc cơ bản

Quyền: người đăng nhập; mặc định chỉ `published` và `active`. Response **200**:
`PageResponse<ItemResponse>`. Không gọi AI, không trả món đã trao trả ở scope public.
Bài đã xóa không xuất hiện trong bất kỳ scope nào, kể cả `mine` và `managed`.

| Query | Ý nghĩa |
| --- | --- |
| `q` | Tìm chuỗi con trong tiêu đề/mô tả, tối đa 200 ký tự, không phân biệt hoa thường; `%`/`_` là ký tự thường |
| `area` | Chuỗi con khu vực, tối đa 200; không âm thầm nới bộ lọc |
| `from`, `until` | Khoảng ngày bao gồm hai đầu; range/exact quy đổi ranh giới ngày UTC+7; loại món không rõ ngày khi lọc ngày |
| `pointId` | Điểm đang thực tế giữ, không phải điểm còn chờ tiếp nhận |
| `scope` | `public` mặc định; `mine` gồm tin do mình đăng/đang giữ, kể cả draft/hidden/returned; `managed` gồm nơi mình có quyền quản lý/nhận/trả hiện tại |
| `page`, `pageSize` | Theo quy ước chung |

Ví dụ: `GET /api/items?q=ví&area=Công%20viên&from=2026-10-01&until=2026-10-24`.
Ngày bắt đầu sau ngày kết thúc, from=0001-01-01, until=9999-12-31, scope lạ hoặc quá giới hạn trả **400**.
Đây là lọc chuỗi, không tuyên bố hiểu đồng nghĩa hay xếp hạng semantic.

## GET /api/items/{id} — chi tiết và cách nhận

Response **200** `ItemResponse`. Người ngoài chỉ đọc món published/active. Người đăng
hoặc người giữ/nhân viên điểm có quyền hiện tại đọc được phần metadata của tin riêng.
Không có/đã xóa/không được đọc: **404**. Cá nhân → gửi claim; điểm → đến xác minh tại điểm;
nơi ngoài hệ thống → làm theo địa chỉ/hướng dẫn. Mở chi tiết không ghi nhận trao trả.

## POST /api/items — đăng món đồ

Body: `{ "content": <ItemInput>, "custody": <CustodyInput> }`.
Response **201**, `Location: /api/items/{id}`, `ItemResponse` ở trạng thái `draft`.
Lưu item + registered event + outbox tombstone + idempotency trong cùng transaction.
Có thể lưu metadata thành bản nháp trước khi upload ảnh để không mất nội dung khi AI lỗi.
Để công khai, tin phải có mô tả hợp lệ và ít nhất một ảnh đã xử lý, được duyệt.

Ba body `custody` được phép:

```json
{"kind":"person"}
```

```json
{"kind":"external","name":"Quầy thư viện","address":"Địa chỉ công khai","instructions":"Hỏi lễ tân"}
```

```json
{"kind":"point","pointId":"<uuid>","confirmedPhysicalReceipt":false}
```

`person` luôn lấy người giữ từ phiên. `external` cần tên 1–200, địa chỉ 1–500;
hướng dẫn tối đa 2000. Không trộn các trường giữa ba loại. Người thường chọn `point`
tạo intake pending, thực tế vẫn `person`; xem `/api/intake-requests` để theo dõi.
Chỉ nhân viên `canReceive` của điểm active được gửi `confirmedPhysicalReceipt:true`
để đăng một món đã thực tế ở điểm. Quyền thiếu **403**, điểm sai/thiếu dữ liệu **400**.

## PUT /api/items/{id} — thay nội dung và câu hỏi

Body: `{ "rowVersion": 2, "content": <ItemInput> }`. Response **200** `ItemResponse`.
Người giữ cá nhân, người đăng nơi ngoài hệ thống hoặc nhân viên `canReceive` tại điểm
hiện tại mới được sửa (**403** nếu thiếu quyền). Không sửa trực tiếp nơi giữ bằng PUT.
Món đã trả/version cũ **409**. Tăng content/row/document version và ghi outbox nguyên tử.

## DELETE /api/items/{id} — xóa bài đăng nhặt được

Body: `{ "rowVersion": 2 }`. Gửi cookie, `X-CSRF-TOKEN` và `Idempotency-Key` theo
quy ước ghi dữ liệu. Response **204**, không có body. Cùng key/payload đã thành công
trả lại **204**; key dùng cho thao tác hoặc payload khác trả **409**.

Quyền như PUT item: người đang giữ cá nhân, người đăng nơi ngoài hệ thống hoặc nhân viên
`canReceive` tại điểm hiện tại. Người đăng ban đầu không tự có quyền xóa sau khi đã giao
món vào điểm. Thiếu quyền **403**, không có/đã xóa **404**, `rowVersion` cũ **409**.
Cho phép xóa cả bài nháp, đang công khai, đang ẩn hoặc đã trao trả.

Đây là xóa mềm: đặt lifecycle `deleted`, tăng row/document version và ghi search
tombstone cùng idempotency key trong một transaction. Bài biến mất khỏi mọi danh sách
item, chi tiết và tìm kiếm; không được sửa, công khai lại, đọc ảnh hoặc tiếp tục claim,
tiếp nhận, trao trả. Claim cũ và intake còn pending được đánh dấu stale; hội thoại cũ chỉ đọc.
Hai bên hội thoại vẫn đọc được tin nhắn theo quyền đã có. Bản ghi item, ảnh, yêu cầu,
tin nhắn và lịch sử custody được giữ trong hệ thống; thao tác này không xóa toàn bộ dữ liệu.

## PUT /api/items/{id}/publication — công khai hoặc ẩn

Body: `{ "rowVersion": 2, "state": "published" }`, hoặc `state:"hidden"`.
Response **200** `ItemResponse`; quyền như PUT item. Công khai yêu cầu ít nhất một
ảnh chưa gỡ có output processed/validated, processingState `ready`, reviewState `approved`.
Không có ảnh đủ điều kiện trả **409**; ảnh chưa duyệt vẫn riêng tư. Bản nháp được tạo
trước để lấy item ID cho bước upload, không được công khai chỉ bằng mô tả.
Ẩn ghi tombstone, không xóa claim/chat/lịch sử. Món đã trả/version cũ **409**.

## GET /api/items/{id}/verification-questions — bộ câu hỏi hiện tại

Quyền đọc item và custody `person`. Response **200** object
`{"contentVersion":1,"questions":[{"slot":1,"questionText":"Đặc điểm riêng?"}]}`;
không có câu hỏi vẫn trả `contentVersion` và `questions:[]`.
Không trả câu trả lời. Món tại điểm/nơi ngoài hệ thống **409**, không được đọc **404**.

## POST /api/items/{id}/claims — gửi yêu cầu nhận

Body: `{"contentVersion":1}` hoặc
`{"contentVersion":1,"answers":[{"slot":1,"answerText":"Mô tả riêng tư"}]}`.
Lấy `contentVersion` từ response bộ câu hỏi; thiếu/sai định dạng **400**, nội dung đã
đổi từ lúc tải câu hỏi **409**. Tải lại bộ câu hỏi và trả lời theo câu hỏi mới trước khi gửi lại.
Response **201** `ClaimResponse`, `Location: /api/claims/{id}`.
Chỉ món published/active do cá nhân giữ; không được tự claim món mình đăng hoặc đang giữ (**400**).
Claimant/reviewer/custody version lấy từ phiên và item bị khóa, không nhận từ client.
Slot phải nằm trong bộ câu hỏi hiện tại, không trùng; câu trả lời tối đa 2000 ký tự,
null/rỗng được lưu null. Luôn snapshot đủ bộ câu hỏi, kể cả câu chưa trả lời.
Đã có pending/approved của cùng claimant và phiên custody **409**; sai slot **400**;
món không khả dụng **404**, custody khác person **409**.

`ClaimResponse`: `id,itemId,claimantUserId,reviewerUserId,status,stale,createdAt,
decidedAt,decisionNote,conversationId,answers`. Mỗi answer gồm
`slot,questionText,answerText`. Đây là DTO riêng tư, không đưa vào public/search.

## GET /api/claims — yêu cầu của mình

Query `itemId` tùy chọn, `page`, `pageSize`. Response **200** `PageResponse<ClaimResponse>`.
Claimant thấy yêu cầu của mình. Reviewer chỉ thấy bằng chứng khi còn là người giữ ở
đúng phiên custody. Không tự cấp bằng chứng cho người giữ mới/nhân viên điểm mới.

## GET /api/claims/{id} — chi tiết bằng chứng

Response **200** `ClaimResponse`, quyền như danh sách; người không thuộc phạm vi **404**.
`stale:true` khi đổi phiên nơi giữ hoặc món đã trả/đã xóa; claim không tự bị hủy.

## POST /api/claims/{id}/decision — duyệt hoặc từ chối

Body: `{"decision":"approved","note":"Ghi chú riêng tư, tối đa 2000 ký tự"}`
hoặc `decision:"rejected"`. Response **200** `ClaimResponse`. Chỉ reviewer còn đang
giữ món mới được xét (**403**); pending + active + đúng custody version (**409** nếu sai).
Approved tạo một conversation cùng transaction; rejected không tạo conversation.
**Cho duyệt nhiều claimant**, theo lựa chọn của chủ dự án. Approved không có nghĩa đã trả.
Không có API thu hồi/rút claim trong phiên bản này.

## GET /api/conversations — hội thoại được phép đọc

Query `page`, `pageSize`. Response **200** `PageResponse<ConversationResponse>`.
Chỉ trả chat của claim approved mà người gọi là claimant/reviewer bất biến.
DTO: `id,itemId,claimantUserId,reviewerUserId,canSend,createdAt`.

## GET /api/conversations/{id} — quyền chat hiện tại

Response **200** `ConversationResponse`; pending/rejected/không thuộc hai bên **404**.
`id` chính là claim ID. Sau đổi nơi giữ, trao trả hoặc xóa bài, `canSend:false`, hai bên vẫn
đọc lịch sử. Ẩn bài đăng đơn thuần không thu hồi quyền chat của hai bên.

## GET /api/conversations/{id}/messages — lịch sử và đọc bù

Query `after>=0` (message sequence cuối đã nhận, mặc định 0), `limit=1..100` (mặc định 50).
Response **200** `{"items":[<MessageResponse>],"nextAfter":123,"hasMore":false}`.
Tin sắp theo sequence tăng dần, điều kiện `sequence > after`. Quyền như chi tiết chat,
không thuộc hai bên **404**. Không dùng số thứ tự mảng làm cursor.

## POST /api/conversations/{id}/messages — gửi tin

Body: `{"clientMessageId":"<uuid khác 0>","body":"Hẹn gặp tại quầy lúc 18:00"}`.
Response **200** `MessageResponse`:
`id,conversationId,senderUserId,clientMessageId,sequence,body,createdAt`.
Nội dung sau trim 1–4000. Sender lấy từ phiên. Gửi cùng mã/nội dung trả tin cũ;
cùng mã khác nội dung **409**. Chat chỉ đọc **409**, không phải người tham gia hoặc bài đã xóa **404**.
Khóa item rồi conversation **trước INSERT**, commit trước response; sequence phản ánh
thứ tự commit trong cùng chat, có thể có khoảng trống do rollback. Dùng HTTP polling
và endpoint đọc bù; chưa cung cấp SignalR/push hoặc đính kèm.

## POST /api/items/{id}/intake-requests — đề nghị chuyển vào điểm

Body: `{"targetPointId":"<uuid>","rowVersion":2}`. Response **201** `IntakeResponse`,
`Location: /api/intake-requests/{id}`. Quyền quản lý item hiện tại. Lưu `pending` và
source custody version; **không đổi nơi giữ, rowVersion hoặc lịch sử custody**.
Trùng request pending cùng điểm/phiên custody, điểm đã đang giữ, version cũ/đã trả **409**;
điểm ngừng hoạt động/không có **400**, thiếu quyền **403**.

`IntakeResponse`: `id,itemId,requestedBy,targetPointId,status,stale,createdAt,decidedAt,
decisionNote,itemRowVersion`. `itemRowVersion` là phiên bản hiện tại của món đồ, dùng làm
`rowVersion` khi xét tiếp nhận, kể cả khi tin đang nháp/ẩn và nhân viên điểm đích chưa được
đọc chi tiết món đồ. `stale` chỉ áp dụng request còn pending khi custody/lifecycle không còn khớp.

## GET /api/intake-requests — hàng đợi của mình/điểm

Query `pointId` tùy chọn, `page`, `pageSize`. Response **200** `PageResponse<IntakeResponse>`.
Người đề nghị thấy request của mình; nhân viên `canReceive` chưa thu hồi thấy request
của đúng điểm active. Không có API tự cấp quyền nhân viên.

## GET /api/intake-requests/{id} — chi tiết tiếp nhận

Response **200** `IntakeResponse`; quyền như danh sách, ngoài phạm vi **404**.
Quyền được kiểm tra lại cả khi phát lại bằng idempotency key cũ.

## POST /api/intake-requests/{id}/decision — tiếp nhận thực tế/từ chối

Body: `{"decision":"received","rowVersion":2,"confirmedPhysicalReceipt":true,"note":"Đã nhận tại quầy"}`
hoặc `{"decision":"rejected","rowVersion":2,"note":"Điểm không thể tiếp nhận"}`.
Response **200** `IntakeResponse`. Nhân viên `canReceive` tại điểm đích active mới được
xét (**403**). Thiếu xác nhận cầm giữ **400**. Đã xét, stale, version cũ/đã trả **409**.
Received cập nhật request + nơi giữ point + custody/row/document version + received
event + snapshot/outbox trong một transaction. Rejected không sửa nơi giữ.

## POST /api/items/{id}/return — xác nhận trao trả thực tế

```json
{
  "rowVersion": 3,
  "confirmedPhysicalHandover": true,
  "claimId": "<claim approved nếu cá nhân giữ>",
  "recipientUserId": null,
  "verificationNote": "Đã xác minh trực tiếp"
}
```

Response **201** `CustodyEventResponse`, Location trỏ lịch sử món đồ.

| Nơi giữ | Quyền và bằng chứng |
| --- | --- |
| Person | Người đang giữ; claim approved đúng món/phiên custody; recipient suy ra từ claimant, nếu gửi phải khớp |
| Point | Nhân viên `canReturn` tại đúng điểm active; không dùng claim; ghi chú xác minh 1–2000 bắt buộc; recipient có thể null nếu người nhận không có tài khoản |
| External | Người đăng; không dùng claim; chỉ ghi nhận sau xác nhận bàn giao thực tế |

Mọi nhánh cần `confirmedPhysicalHandover:true`. Thời điểm sự kiện do server ghi UTC;
không nhận thời gian/actor tùy ý. Recipient được chỉ định phải là tài khoản còn hiệu lực.
Sai quyền **403**, thiếu xác nhận/bằng chứng **400**, version cũ/claim sai/đã trả **409**.
Lifecycle + một returned event + phiên bản + tombstone + key ghi nguyên tử. Nhiều claim
approved vẫn chỉ một lần return. Khi nhận vào điểm và trả đồng thời chỉ một thao tác thắng.
Giữ cột custody là nơi giữ cuối trước khi trả; không biến recipient thành người giữ mới.

## GET /api/items/{id}/custody-events — lịch sử quản lý

Query `page`, `pageSize`. Response **200** `PageResponse<CustodyEventResponse>`;
DTO `id,itemId,eventKind,custodyVersion,occurredAt`. Chỉ tác giả hoặc người giữ/nhân viên
điểm hiện có quyền nhận/trả; người khác **403**. Không có API sửa/xóa sự kiện.
Không trả verification note, recipient, câu trả lời hoặc bản chụp custody riêng tư.

## Kiểm thử

Chạy `make api-integration`. [RecoveryChecks.cs](../../apps/api/tests/integration/RecoveryChecks.cs)
kiểm tra các luồng nghiệp vụ qua HTTP + PostgreSQL dùng một lần, gồm
claim 0 câu hỏi, bộ câu hỏi đổi trước khi gửi, nhiều approved, immutable answers, CSRF, stale version, phân quyền,
replay, thứ tự tin nhắn, tiếp nhận và trao trả đồng thời.
[ItemDeletionChecks.cs](../../apps/api/tests/integration/ItemDeletionChecks.cs) kiểm tra xóa bài,
phân quyền quản lý, phiên bản cũ, ẩn khỏi danh sách/chi tiết/tìm kiếm, giữ lịch sử và chặn
thao tác sau xóa. Xem thêm
[phạm vi kiểm chứng](testing.md) để phân biệt test double và dịch vụ thật.
