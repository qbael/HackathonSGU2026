import { useEffect, useState, type FormEvent } from "react";
import {
  custodyLabels,
  imageUrl,
  uploadImage,
  write,
  type Item,
  type ItemImage,
  type Point,
  type Question,
  type QuestionSet,
} from "../lib/api";
import {
  draftFromItem,
  emptyDraft,
  itemContent,
  itemCustody,
  vietnamLocal,
  type ItemDraft,
} from "../lib/itemForm";
import { validatePostImages } from "../lib/images";
import { useAction, useResource } from "../hooks/hooks";
import { ImagePreviews } from "../components/ImagePreviews";
import {
  Badge,
  ConfirmModal,
  EmptyState,
  ErrorNotice,
  Icon,
  ItemSummary,
  Loading,
  Notice,
  PageHeader,
  useToast,
} from "../components/ui";

export function PostItem({ id }: { id?: string }) {
  const item = useResource<Item>(id ? `/api/items/${id}` : null);
  const questions = useResource<QuestionSet>(
    id && item.data?.custody.kind === "person"
      ? `/api/items/${id}/verification-questions`
      : null,
  );
  if (!id) return <PostEditor />;
  if (item.loading || questions.loading) return <Loading />;
  if (item.error || questions.error)
    return (
      <ErrorNotice
        error={item.error ?? questions.error}
        retry={() => {
          item.reload();
          questions.reload();
        }}
      />
    );
  return (
    item.data && (
      <PostEditor item={item.data} questions={questions.data?.questions ?? []} />
    )
  );
}

function PostEditor({
  item,
  questions = [],
}: {
  item?: Item;
  questions?: Question[];
}) {
  const [draft, setDraft] = useState<ItemDraft>(() =>
    item ? draftFromItem(item, questions) : { ...emptyDraft, questions: [] },
  );
  const [step, setStep] = useState(1);
  const [files, setFiles] = useState<File[]>([]);
  const [created, setCreated] = useState<Item | null>(null);
  const [uploading, setUploading] = useState("");
  const action = useAction();
  const points = useResource<Point[]>(
    draft.kind === "point" && !item ? "/api/reception-points" : null,
  );
  function update<K extends keyof ItemDraft>(key: K, value: ItemDraft[K]) {
    setDraft((previous) => ({ ...previous, [key]: value }));
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!item) {
      try {
        validatePostImages(files);
      } catch (cause) {
        action.setError(cause as Error);
        setStep(1);
        return;
      }
    }
    if (step < 3) {
      setStep(step + 1);
      document.getElementById("post-heading")?.focus();
      return;
    }
    await action.run(async () => {
      const content = itemContent(draft);
      const saved = item
        ? await write<Item>(
            `/api/items/${item.id}`,
            { rowVersion: item.rowVersion, content },
            "PUT",
          )
        : await write<Item>("/api/items", {
            content,
            custody: itemCustody(draft),
          });
      setCreated(saved);
      try {
        for (let index = 0; index < files.length; index++) {
          setUploading(`Đang xử lý ảnh ${index + 1}/${files.length}…`);
          await uploadImage(saved.id, files[index], index + 1);
        }
        window.location.assign(`/items/${saved.id}/review`);
      } finally {
        setFiles([]);
        setUploading("");
      }
      return saved;
    });
  }
  return (
    <>
      <PageHeader
        eyebrow="Một hành động nhỏ, một niềm vui lớn"
        title={item ? "Chỉnh sửa tin nhặt được" : "Đăng tin đồ nhặt được"}
      >
        Mô tả những đặc điểm dễ nhận ra. Giữ lại thông tin riêng để xác minh
        đúng chủ sở hữu.
      </PageHeader>
      {created ? (
        <section className="panel saved-panel">
          <span className="empty-icon">
            <Icon name="check" size={30} />
          </span>
          <h2>Tin của bạn đã được lưu</h2>
          <p>
            {uploading ||
              "Tiếp tục kiểm tra ảnh và công khai tin khi sẵn sàng."}
          </p>
          <ErrorNotice error={action.error} />
          {action.busy ? (
            <Loading />
          ) : (
            <a className="button" href={`/items/${created.id}/review`}>
              Tiếp tục duyệt ảnh & công khai
              <Icon name="arrow" size={17} />
            </a>
          )}
        </section>
      ) : (
        <>
          <ol className="stepper" aria-label="Các bước đăng tin">
            {[
              "Ảnh & thông tin món đồ",
              "Nơi lưu giữ hiện tại",
              draft.kind === "person" ? "Câu hỏi xác minh" : "Kiểm tra tin đăng",
            ].map((label, index) => (
              <li
                key={label}
                className={
                  step === index + 1
                    ? "current"
                    : step > index + 1
                      ? "complete"
                      : ""
                }
                aria-current={step === index + 1 ? "step" : undefined}
              >
                <span>
                  {step > index + 1 ? (
                    <Icon name="check" size={16} />
                  ) : (
                    index + 1
                  )}
                </span>
                <div>
                  <small>Bước {index + 1}</small>
                  <strong>{label}</strong>
                </div>
              </li>
            ))}
          </ol>
          <div className="post-layout">
            <form
              className="panel post-form"
              onSubmit={(event) => void submit(event)}
            >
              <div className="panel-title">
                <div>
                  <p className="eyebrow">Bước {step} / 3</p>
                  <h2 id="post-heading" tabIndex={-1}>
                    {step === 1
                      ? "Kể một chút về món đồ"
                      : step === 2
                        ? "Bạn đang giữ món đồ ở đâu?"
                        : draft.kind === "person"
                          ? "Thiết lập câu hỏi xác minh"
                          : "Kiểm tra trước khi đăng"}
                  </h2>
                </div>
                <Icon
                  name={
                    step === 1
                      ? "document"
                      : step === 2
                        ? "pin"
                        : draft.kind === "person"
                          ? "lock"
                          : "shield"
                  }
                  size={26}
                />
              </div>
              {step === 1 && (
                <div className="form-stack">
                  <label>
                    Tên món đồ <span className="required">*</span>
                    <input
                      value={draft.title}
                      onChange={(event) => update("title", event.target.value)}
                      required
                      maxLength={200}
                      placeholder="Ví dụ: Ví da đen khóa kéo vàng"
                    />
                  </label>
                  {!item && (
                    <div>
                      <label className="upload-zone">
                        <Icon name="upload" size={28} />
                        <strong>
                          Thêm ảnh món đồ <span className="required">*</span>
                        </strong>
                        <span>JPEG, PNG, WebP · từ 1 đến 3 ảnh, 10 MB/ảnh</span>
                        <input
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          multiple
                          disabled={files.length >= 3}
                          required={!files.length}
                          onChange={(event) => {
                            const incoming = Array.from(
                              event.target.files ?? [],
                            );
                            event.target.value = "";
                            if (!incoming.length) return;
                            const selected = [...files, ...incoming];
                            try {
                              validatePostImages(selected);
                              setFiles(selected);
                              action.setError(null);
                            } catch (cause) {
                              action.setError(cause as Error);
                            }
                          }}
                        />
                        {files.length > 0 && (
                          <span>
                            {files.length} ảnh đã chọn · Chưa công khai
                          </span>
                        )}
                      </label>
                      <ImagePreviews
                        files={files}
                        onRemove={(index) => {
                          setFiles((current) =>
                            current.filter((_, position) => position !== index),
                          );
                          action.setError(null);
                        }}
                      />
                      <p className="field-hint">
                        Tin cần ít nhất 1 ảnh kèm mô tả. Ảnh sẽ được xử lý sau
                        khi lưu tin; bạn cần duyệt ảnh trước khi công khai.
                      </p>
                    </div>
                  )}
                  <label>
                    Mô tả công khai <span className="required">*</span>
                    <textarea
                      value={draft.description}
                      onChange={(event) =>
                        update("description", event.target.value)
                      }
                      required
                      maxLength={5000}
                      rows={4}
                      placeholder="Ví da đen, nhặt tại phòng E.205 hoặc sảnh hội trường A…"
                    />
                    <span className="field-hint">
                      Có thể bổ sung nơi nhặt cụ thể, như phòng E.205 hoặc sảnh hội
                      trường A của Trường Đại học Sài Gòn. Không ghi số giấy tờ, số
                      tài khoản hoặc chi tiết bí mật bên trong.
                    </span>
                  </label>
                  <label>
                    Khu vực nhặt được <span className="required">*</span>
                    <input
                      value={draft.area}
                      onChange={(event) => update("area", event.target.value)}
                      required
                      maxLength={200}
                      placeholder="Ví dụ: Trường Đại học Sài Gòn"
                    />
                  </label>
                  <label>
                    Thời gian nhặt được
                    <select
                      value={draft.precision}
                      onChange={(event) =>
                        update(
                          "precision",
                          event.target.value as ItemDraft["precision"],
                        )
                      }
                    >
                      <option value="unknown">Không nhớ chính xác</option>
                      <option value="date">Nhớ ngày nhặt được</option>
                      <option value="exact">Nhớ ngày và giờ</option>
                      <option value="range">Trong một khoảng thời gian</option>
                    </select>
                  </label>
                  {draft.precision === "date" && (
                    <label>
                      Ngày nhặt được
                      <input
                        type="date"
                        required
                        max={vietnamLocal(new Date().toISOString()).slice(
                          0,
                          10,
                        )}
                        value={draft.date}
                        onChange={(event) => update("date", event.target.value)}
                      />
                    </label>
                  )}
                  {(draft.precision === "exact" ||
                    draft.precision === "range") && (
                    <div className="form-row">
                      <label>
                        {draft.precision === "range"
                          ? "Từ thời điểm"
                          : "Ngày giờ nhặt được"}
                        <input
                          type="datetime-local"
                          required
                          value={draft.from}
                          max={vietnamLocal(new Date().toISOString())}
                          onChange={(event) =>
                            update("from", event.target.value)
                          }
                        />
                      </label>
                      {draft.precision === "range" && (
                        <label>
                          Đến thời điểm
                          <input
                            type="datetime-local"
                            required
                            min={draft.from}
                            max={vietnamLocal(new Date().toISOString())}
                            value={draft.until}
                            onChange={(event) =>
                              update("until", event.target.value)
                            }
                          />
                        </label>
                      )}
                    </div>
                  )}
                  {draft.precision !== "unknown" && (
                    <p className="field-hint">Thời gian Việt Nam (UTC+7).</p>
                  )}
                </div>
              )}
              {step === 2 && (
                <div className="form-stack">
                  {item ? (
                    <Notice>
                      Nơi giữ hiện tại:{" "}
                      <strong>{custodyLabels[item.custody.kind]}</strong>. Muốn
                      gửi món đồ vào Hub, dùng chức năng chuyển điểm tiếp nhận ở
                      bài đăng.
                    </Notice>
                  ) : (
                    <>
                      <div className="custody-options">
                        {(
                          [
                            [
                              "person",
                              "Tôi đang tự giữ",
                              "Bạn đối chiếu yêu cầu và hẹn gặp để trao trả.",
                            ],
                            [
                              "point",
                              "Đề nghị gửi vào Findie Hub",
                              "Bạn vẫn giữ đồ cho đến khi nhân viên xác nhận đã tiếp nhận tại quầy.",
                            ],
                            [
                              "external",
                              "Đã gửi tại nơi ngoài hệ thống",
                              "Cung cấp tên và địa chỉ công khai của đơn vị đang giữ.",
                            ],
                          ] as const
                        ).map(([kind, title, detail]) => (
                          <label
                            className={`choice-card${draft.kind === kind ? " selected" : ""}`}
                            key={kind}
                          >
                            <input
                              type="radio"
                              name="custody"
                              checked={draft.kind === kind}
                              onChange={() => update("kind", kind)}
                            />
                            <span>
                              <strong>{title}</strong>
                              <small>{detail}</small>
                            </span>
                            <Icon
                              name={kind === "person" ? "user" : "building"}
                              size={22}
                            />
                          </label>
                        ))}
                      </div>
                      {draft.kind === "point" && (
                        <>
                          <ErrorNotice
                            error={points.error}
                            retry={points.reload}
                          />
                          {points.loading ? (
                            <Loading />
                          ) : (
                            <label>
                              Chọn điểm tiếp nhận
                              <select
                                required
                                value={draft.pointId}
                                onChange={(event) =>
                                  update("pointId", event.target.value)
                                }
                              >
                                <option value="">Chọn Findie Hub</option>
                                {points.data?.map((point) => (
                                  <option key={point.id} value={point.id}>
                                    {point.name} — {point.publicAddress}
                                  </option>
                                ))}
                              </select>
                            </label>
                          )}
                          <Notice tone="warning">
                            Đây là đề nghị tiếp nhận. Hãy trực tiếp mang món đồ
                            đến quầy; nơi giữ chỉ thay đổi sau khi nhân viên
                            nhận đồ.
                          </Notice>
                        </>
                      )}
                      {draft.kind === "external" && (
                        <>
                          <label>
                            Tên nơi đang giữ
                            <input
                              required
                              maxLength={200}
                              value={draft.externalName}
                              onChange={(event) =>
                                update("externalName", event.target.value)
                              }
                              placeholder="Ví dụ: Quầy bảo vệ nhà văn hóa"
                            />
                          </label>
                          <label>
                            Địa chỉ công khai
                            <input
                              required
                              maxLength={500}
                              value={draft.address}
                              onChange={(event) =>
                                update("address", event.target.value)
                              }
                            />
                          </label>
                          <label>
                            Hướng dẫn đến nhận
                            <textarea
                              maxLength={2000}
                              rows={3}
                              value={draft.instructions}
                              onChange={(event) =>
                                update("instructions", event.target.value)
                              }
                              placeholder="Vị trí quầy, giờ làm việc hoặc giấy tờ cần mang theo…"
                            />
                          </label>
                        </>
                      )}
                    </>
                  )}
                </div>
              )}
              {step === 3 && (
                <div className="form-stack">
                  {draft.kind === "person" ? (
                    <>
                      <Notice>
                        <strong>
                          Câu hỏi chỉ chủ sở hữu thật mới trả lời được.
                        </strong>
                        <p>
                          Đặt tối đa 3 câu hỏi, không cần nhập đáp án. Bạn sẽ tự đối
                          chiếu với món đồ khi xét yêu cầu.
                        </p>
                      </Notice>
                      {draft.questions.map((question, index) => (
                        <div className="question-field" key={index}>
                          <label>
                            Câu hỏi {index + 1}
                            <textarea
                              required
                              rows={2}
                              maxLength={500}
                              value={question}
                              onChange={(event) =>
                                update(
                                  "questions",
                                  draft.questions.map((value, at) =>
                                    at === index ? event.target.value : value,
                                  ),
                                )
                              }
                              placeholder="Ví dụ: Móc khóa có hình gì?"
                            />
                          </label>
                          <button
                            className="icon-button"
                            type="button"
                            aria-label={`Xóa câu hỏi ${index + 1}`}
                            onClick={() =>
                              update(
                                "questions",
                                draft.questions.filter((_, at) => at !== index),
                              )
                            }
                          >
                            <Icon name="close" size={17} />
                          </button>
                        </div>
                      ))}
                      {draft.questions.length < 3 && (
                        <button
                          className="button button-secondary"
                          type="button"
                          onClick={() =>
                            update("questions", [...draft.questions, ""])
                          }
                        >
                          <Icon name="plus" size={17} />
                          Thêm câu hỏi xác minh
                        </button>
                      )}
                      <p className="field-hint">
                        Bạn có thể để trống phần câu hỏi. Người tìm vẫn được gửi
                        yêu cầu nhận đồ.
                      </p>
                    </>
                  ) : (
                    <Notice>
                      Món đồ tại điểm tiếp nhận hoặc nơi ngoài hệ thống được
                      xác minh trực tiếp khi nhận đồ.
                    </Notice>
                  )}
                  <label className="checkbox-field">
                    <input type="checkbox" required />
                    Tôi đã kiểm tra mô tả công khai và không để lộ thông tin cá
                    nhân nhạy cảm.
                  </label>
                </div>
              )}
              <ErrorNotice error={action.error} />
              <div className="form-actions">
                {step > 1 ? (
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={action.busy}
                    onClick={() => setStep(step - 1)}
                  >
                    <Icon name="back" size={16} />
                    Quay lại
                  </button>
                ) : (
                  <a className="text-button" href="/posts">
                    Hủy
                  </a>
                )}
                <button className="button" type="submit" disabled={action.busy}>
                  {action.busy
                    ? "Đang lưu tin…"
                    : step < 3
                      ? "Tiếp tục"
                      : "Lưu tin & kiểm tra ảnh"}
                  <Icon name="arrow" size={17} />
                </button>
              </div>
            </form>
            <aside className="post-aside">
              <section className="panel">
                <span className="empty-icon">
                  <Icon name="shield" size={28} />
                </span>
                <h3>Một tin đăng có ích bắt đầu từ sự cẩn thận.</h3>
                <ol className="tips-list">
                  <li>Chụp rõ đồ vật, tránh để lộ giấy tờ và số thẻ.</li>
                  <li>Mô tả đặc điểm bên ngoài để người mất nhận ra.</li>
                  <li>Giữ lại chi tiết riêng để đối chiếu đúng chủ sở hữu.</li>
                </ol>
              </section>
              <Notice>
                Không lưu ảnh gốc vào hồ sơ công khai. Chỉ bản ảnh đã xử lý và
                được duyệt mới hiển thị.
              </Notice>
            </aside>
          </div>
        </>
      )}
    </>
  );
}

export function ReviewImages({ id }: { id: string }) {
  const toast = useToast();
  const [retireConfirmOpen, setRetireConfirmOpen] = useState(false);
  const item = useResource<Item>(`/api/items/${id}`);
  const images = useResource<ItemImage[]>(`/api/items/${id}/images`);
  const [selectedId, setSelectedId] = useState("");
  const [checks, setChecks] = useState<boolean[]>([false, false, false]);
  const [previewReady, setPreviewReady] = useState(false);
  const action = useAction();
  const selected =
    images.data?.find((image) => image.id === selectedId) ??
    images.data?.find((image) => image.previewUrl);
  useEffect(() => {
    setChecks([false, false, false]);
    setPreviewReady(false);
  }, [selected?.id, selected?.contentVersion]);
  function reload() {
    item.reload();
    images.reload();
  }
  async function review(decision: "approved" | "rejected") {
    if (!selected) return;
    const result = await action.run(() =>
      write<ItemImage>(`/api/items/${id}/images/${selected.id}/review`, {
        contentVersion: selected.contentVersion,
        decision,
      }),
    );
    if (result) {
      setChecks([false, false, false]);
      reload();
    }
  }
  if (item.loading || images.loading) return <Loading />;
  if (item.error || images.error)
    return <ErrorNotice error={item.error ?? images.error} retry={reload} />;
  if (!item.data || !images.data) return null;
  const activeImages = images.data.filter((image) => image.previewUrl);
  const availablePosition =
    activeImages.length < 3
      ? [1, 2, 3].find(
          (position) => !activeImages.some((image) => image.position === position),
        )
      : undefined;
  return (
    <>
      <PageHeader
        eyebrow="Kiểm tra trước khi công khai"
        title="Duyệt bản ảnh của món đồ"
      >
        Chỉ xem bản ảnh đã qua xử lý. Hãy kiểm tra thông tin nhạy cảm trước khi
        duyệt.
      </PageHeader>
      <ItemSummary item={item.data} />
      <ErrorNotice error={action.error} />
      <div className="review-layout">
        <section className="panel review-canvas">
          <div className="panel-title">
            <h2>Bản ảnh đã xử lý</h2>
            {selected && <Badge value={selected.processingState} />}
          </div>
          {selected && imageUrl(selected.previewUrl) ? (
            <img
              className="processed-image"
              src={imageUrl(selected.previewUrl)}
              alt="Bản ảnh đã xử lý để kiểm tra trước khi công khai"
              onLoad={() => setPreviewReady(true)}
              onError={() => {
                setPreviewReady(false);
                action.setError(
                  new Error(
                    "Chưa tải được bản ảnh đã xử lý. Vui lòng tải lại để kiểm tra.",
                  ),
                );
              }}
            />
          ) : (
            <EmptyState title="Chưa có bản ảnh để duyệt">
              <p>Thêm ít nhất 1 ảnh, kiểm tra và duyệt ảnh để công khai tin.</p>
            </EmptyState>
          )}
          {images.data.some((image) => image.previewUrl) && (
            <div className="review-thumbnails">
              {images.data
                .filter((image) => image.previewUrl)
                .map((image) => (
                  <button
                    type="button"
                    key={image.id}
                    aria-pressed={selected?.id === image.id}
                    onClick={() => setSelectedId(image.id)}
                  >
                    <img
                      src={imageUrl(image.previewUrl)}
                      alt={`Ảnh ${image.position}`}
                    />
                    <Badge value={image.reviewState} />
                  </button>
                ))}
            </div>
          )}
          {availablePosition && item.data.lifecycle === "active" && (
            <label className="button button-secondary upload-button">
              <Icon name="upload" size={17} />
              {action.busy ? "Đang xử lý ảnh…" : "Thêm ảnh món đồ"}
              <input
                type="file"
                disabled={action.busy}
                accept="image/jpeg,image/png,image/webp"
                onChange={async (event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (!file) return;
                  const result = await action.run(() =>
                    uploadImage(id, file, availablePosition),
                  );
                  if (result) {
                    setSelectedId(result.id);
                    reload();
                  }
                }}
              />
            </label>
          )}
        </section>
        <aside className="panel review-checklist">
          <p className="eyebrow">Kiểm tra an toàn</p>
          <h2>Thông tin riêng đã được che?</h2>
          <p className="muted">
            Nếu ảnh còn để lộ dữ liệu cá nhân, từ chối ảnh và tải lại ảnh phù
            hợp.
          </p>
          {[
            "Số hộ chiếu đã che toàn bộ; số CCCD/CMND, điện thoại và mã định danh khác đã che phần đầu, chỉ giữ tối đa khoảng 40% phần cuối để đối chiếu.",
            "Không lộ khuôn mặt, ảnh chân dung, chữ ký, địa chỉ riêng, quê quán hoặc nơi sinh.",
            "Không lộ vùng mã đọc máy (MRZ) trên hộ chiếu, mã QR, mã vạch hoặc chi tiết xác minh bí mật.",
          ].map((label, index) => (
            <label className="checkbox-field safety-check" key={label}>
              <input
                type="checkbox"
                checked={checks[index]}
                disabled={
                  action.busy ||
                  !selected ||
                  !previewReady ||
                  selected.reviewState === "approved"
                }
                onChange={(event) =>
                  setChecks((values) =>
                    values.map((value, at) =>
                      at === index ? event.target.checked : value,
                    ),
                  )
                }
              />
              <span>{label}</span>
            </label>
          ))}
          {selected?.reviewState === "approved" && (
            <Notice tone="success">Ảnh này đã được duyệt.</Notice>
          )}
          {selected && (
            <div className="form-stack">
              <button
                className="button button-wide"
                type="button"
                disabled={
                  action.busy ||
                  !previewReady ||
                  !checks.every(Boolean) ||
                  selected.reviewState === "approved" ||
                  !["needs_review", "ready"].includes(selected.processingState)
                }
                onClick={() => void review("approved")}
              >
                <Icon name="check" size={17} />
                Duyệt ảnh công khai
              </button>
              <button
                className="button button-secondary"
                type="button"
                disabled={action.busy || selected.reviewState === "rejected"}
                onClick={() => void review("rejected")}
              >
                Từ chối ảnh
              </button>
              <button
                className="text-button danger-text"
                type="button"
                disabled={action.busy}
                onClick={() => setRetireConfirmOpen(true)}
              >
                Gỡ ảnh khỏi tin
              </button>
            </div>
          )}
          <div className="publication-actions">
            <Notice>
              Tin cần mô tả và ít nhất 1 ảnh đã được duyệt để công khai.
              Nếu từ chối hoặc gỡ ảnh công khai cuối cùng, tin sẽ tự động ẩn.
            </Notice>
            {item.data.publicationState === "published" ? (
              <a className="button button-wide" href={`/items/${id}`}>
                Xem tin công khai
                <Icon name="arrow" size={17} />
              </a>
            ) : (
              <button
                className="button button-wide"
                type="button"
                disabled={
                  action.busy ||
                  item.data.lifecycle !== "active" ||
                  !item.data.images.length
                }
                onClick={async () => {
                  const result = await action.run(() =>
                    write<Item>(
                      `/api/items/${id}/publication`,
                      { rowVersion: item.data!.rowVersion, state: "published" },
                      "PUT",
                    ),
                  );
                  if (result) window.location.assign("/posts");
                }}
              >
                Công khai tin
                <Icon name="arrow" size={17} />
              </button>
            )}
            <a className="text-button" href="/posts">
              Về bài đăng của tôi
            </a>
          </div>
        </aside>
      </div>

      <ConfirmModal
        open={retireConfirmOpen}
        title="Gỡ ảnh khỏi tin"
        message="Gỡ bản ảnh này khỏi tin? Bạn cần tải ảnh khác nếu muốn thay thế."
        confirmText="Gỡ ảnh"
        danger
        busy={action.busy}
        onConfirm={async () => {
          if (!selected) return;
          const result = await action.run(() =>
            write<ItemImage>(
              `/api/items/${id}/images/${selected.id}/retire`,
              { contentVersion: selected.contentVersion },
            ),
          );
          if (result) {
            setSelectedId("");
            reload();
            setRetireConfirmOpen(false);
            toast.success("Đã gỡ ảnh thành công.");
          }
        }}
        onCancel={() => setRetireConfirmOpen(false)}
      />
    </>
  );
}
