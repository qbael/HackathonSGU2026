import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  custodyLabels,
  formatDate,
  pageNumber,
  write,
  type Claim,
  type Conversation,
  type Intake,
  type Item,
  type Message,
  type MessagePage,
  type Page,
  type Point,
  type QuestionSet,
} from "../lib/api";
import type { UserProfile } from "../lib/auth";
import { useAction, useResource } from "../hooks/hooks";
import {
  Badge,
  ConfirmDialog,
  EmptyState,
  ErrorNotice,
  Icon,
  ItemPhoto,
  ItemSummary,
  Loading,
  Notice,
  PageHeader,
  Pagination,
  SafetyNote,
} from "../components/ui";

function LinkedItem({ id }: { id: string }) {
  const item = useResource<Item>(`/api/items/${id}`);
  return item.data ? (
    <ItemSummary item={item.data} />
  ) : (
    <a className="text-button" href={`/items/${id}`}>
      Món đồ #{id.slice(0, 8)}
      <Icon name="arrow" size={15} />
    </a>
  );
}

export function ClaimItem({ id }: { id: string }) {
  const item = useResource<Item>(`/api/items/${id}`);
  const questions = useResource<QuestionSet>(
    item.data?.canClaim ? `/api/items/${id}/verification-questions` : null,
  );
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const action = useAction();
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
  if (!item.data) return null;
  if (!item.data.canClaim)
    return (
      <EmptyState title="Không thể gửi yêu cầu nhận đồ" icon="document">
        <p>
          Chỉ có thể yêu cầu nhận món đồ do người khác đăng và giữ, đang được
          công khai và chưa trao trả.
        </p>
        <a className="button" href={`/items/${id}`}>
          Xem lại món đồ
        </a>
      </EmptyState>
    );
  if (!questions.data) return null;
  return (
    <>
      <PageHeader
        eyebrow="Bước đầu để tìm lại món đồ"
        title="Gửi yêu cầu nhận đồ"
      >
        Cung cấp những chi tiết chỉ bạn biết để người giữ đối chiếu.
      </PageHeader>
      <div className="claim-layout">
        <aside className="form-sidebar">
          <ItemSummary item={item.data} />
          <Notice>
            <strong>Câu trả lời được gửi riêng đến người giữ.</strong>
            <p>Chỉ mở hội thoại sau khi yêu cầu được chấp thuận.</p>
          </Notice>
        </aside>
        <form
          className="panel claim-form"
          onSubmit={async (event) => {
            event.preventDefault();
            const result = await action.run(() =>
              write<Claim>(`/api/items/${id}/claims`, {
                contentVersion: questions.data!.contentVersion,
                answers: questions.data!.questions.map((question) => ({
                  slot: question.slot,
                  answerText: answers[question.slot]?.trim() || null,
                })),
              }),
            );
            if (result) window.location.assign(`/claims/${result.id}`);
          }}
        >
          <p className="eyebrow">Xác minh quyền sở hữu</p>
          <h2>Đây có phải món đồ của bạn?</h2>
          <p className="muted">
            Bạn có thể bỏ qua câu hỏi chưa nhớ rõ. Người giữ sẽ quyết định dựa
            trên thông tin đối chiếu.
          </p>
          {questions.data.questions.length ? (
            questions.data.questions.map((question, index) => (
              <label className="answer-field" key={question.slot}>
                <span>
                  <b>{String(index + 1).padStart(2, "0")}</b>
                  {question.questionText}
                </span>
                <textarea
                  rows={3}
                  maxLength={2000}
                  value={answers[question.slot] ?? ""}
                  onChange={(event) =>
                    setAnswers((values) => ({
                      ...values,
                      [question.slot]: event.target.value,
                    }))
                  }
                  placeholder="Nhập chi tiết mà bạn còn nhớ…"
                />
              </label>
            ))
          ) : (
            <Notice>
              Người giữ không đặt câu hỏi xác minh. Bạn vẫn có thể gửi yêu cầu
              nhận đồ và chờ đối chiếu.
            </Notice>
          )}
          <SafetyNote />
          <ErrorNotice
            error={action.error}
            retry={
              action.error instanceof ApiError && action.error.status === 409
                ? () => {
                    setAnswers({});
                    item.reload();
                    questions.reload();
                    action.setError(null);
                  }
                : undefined
            }
          />
          <div className="form-actions">
            <a className="text-button" href={`/items/${id}`}>
              <Icon name="back" size={16} />
              Xem lại món đồ
            </a>
            <button
              className="button"
              disabled={action.busy || item.data.lifecycle !== "active"}
            >
              {action.busy ? "Đang gửi yêu cầu…" : "Gửi yêu cầu nhận đồ"}
              <Icon name="send" size={17} />
            </button>
          </div>
        </form>
      </div>
    </>
  );
}

export function Requests({ user }: { user: UserProfile }) {
  const query = new URLSearchParams(window.location.search);
  const page = pageNumber(query.get("page"));
  const filter = new URLSearchParams({ page: String(page), pageSize: "10" });
  if (query.get("itemId")) filter.set("itemId", query.get("itemId")!);
  const claims = useResource<Page<Claim>>(`/api/claims?${filter}`);
  return (
    <>
      <PageHeader
        eyebrow="Mỗi kết nối là một cơ hội tìm lại"
        title="Yêu cầu trao trả"
      >
        Theo dõi yêu cầu của bạn và xét duyệt những yêu cầu gửi đến món đồ bạn
        đang giữ.
      </PageHeader>
      <ErrorNotice error={claims.error} retry={claims.reload} />
      {claims.loading && <Loading />}
      {claims.data && (
        <>
          {claims.data.items.length ? (
            <div className="requests-list">
              {claims.data.items.map((claim) => (
                <article className="panel request-card" key={claim.id}>
                  <div className="request-card-top">
                    <span className="eyebrow">
                      {claim.reviewerUserId === user.id
                        ? claim.status === "pending" && !claim.stale
                          ? "Cần bạn xét duyệt"
                          : "Yêu cầu gửi đến bạn"
                        : "Yêu cầu của bạn"}{" "}
                      · {formatDate(claim.createdAt, true)}
                    </span>
                    <Badge value={claim.status} />
                  </div>
                  <LinkedItem id={claim.itemId} />
                  {claim.stale ? (
                    <Notice tone="warning">
                      Nơi giữ hoặc trạng thái món đồ đã thay đổi, hoặc bài đăng
                      đã bị xóa. Yêu cầu này chỉ dùng để tra cứu.
                    </Notice>
                  ) : (
                    <ol className="progress-track">
                      <li className="done">Đã gửi yêu cầu</li>
                      <li
                        className={
                          claim.status !== "pending" ? "done" : "current"
                        }
                      >
                        Người giữ đối chiếu
                      </li>
                      <li className={claim.status === "approved" ? "done" : ""}>
                        Kết nối trao trả
                      </li>
                    </ol>
                  )}
                  <div className="card-actions">
                    <a
                      className="button button-secondary"
                      href={`/claims/${claim.id}`}
                    >
                      {claim.reviewerUserId === user.id &&
                      claim.status === "pending" &&
                      !claim.stale
                        ? "Xét duyệt yêu cầu"
                        : "Xem tiến trình"}
                      <Icon name="arrow" size={16} />
                    </a>
                    {claim.conversationId && (
                      <a
                        className="button"
                        href={`/messages?conversation=${claim.conversationId}`}
                      >
                        <Icon name="chat" size={16} />
                        Mở hội thoại
                      </a>
                    )}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState title="Bạn chưa có yêu cầu trao trả" icon="document">
              <p>
                Khi gửi yêu cầu nhận đồ hoặc có người nhận món đồ bạn đang giữ,
                tiến trình sẽ hiện ở đây.
              </p>
              <a className="button" href="/search">
                Tìm đồ thất lạc
                <Icon name="search" size={17} />
              </a>
            </EmptyState>
          )}
          <Pagination page={claims.data.page} totalPages={claims.data.totalPages} />
        </>
      )}
    </>
  );
}

export function ClaimDetail({ id, user }: { id: string; user: UserProfile }) {
  const claim = useResource<Claim>(`/api/claims/${id}`);
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const action = useAction();
  async function decide(decision: "approved" | "rejected") {
    const result = await action.run(() =>
      write<Claim>(`/api/claims/${id}/decision`, {
        decision,
        note: note.trim() || null,
      }),
    );
    if (result) claim.reload();
  }
  if (claim.loading) return <Loading />;
  if (!claim.data)
    return <ErrorNotice error={claim.error} retry={claim.reload} />;
  const data = claim.data;
  const reviewer = data.reviewerUserId === user.id;
  return (
    <>
      <PageHeader
        eyebrow={`Yêu cầu #${id.slice(0, 8)}`}
        title={
          reviewer ? "Xét duyệt yêu cầu nhận đồ" : "Tiến trình yêu cầu của bạn"
        }
      >
        Gửi lúc {formatDate(data.createdAt, true)}. Đối chiếu cẩn thận để trao
        lại đúng người.
      </PageHeader>
      <div className="claim-layout">
        <aside className="form-sidebar">
          <LinkedItem id={data.itemId} />
          <SafetyNote />
          <a className="text-button" href="/requests">
            <Icon name="back" size={16} />
            Tất cả yêu cầu
          </a>
        </aside>
        <section className="panel claim-form">
          <div className="panel-title">
            <h2>
              {reviewer
                ? "Câu trả lời của người yêu cầu"
                : "Thông tin bạn đã gửi"}
            </h2>
            <Badge value={data.status} />
          </div>
          {data.stale && (
            <Notice tone="warning">
              Món đồ đã đổi nơi giữ, đã được trao trả hoặc bài đăng đã bị xóa.
              Không thể tiếp tục xét duyệt yêu cầu này.
            </Notice>
          )}
          {data.answers.length ? (
            data.answers.map((answer, index) => (
              <div className="answer-review" key={answer.slot}>
                <p className="eyebrow">Câu hỏi {index + 1}</p>
                <h3>{answer.questionText}</h3>
                <p className="preserve-lines">
                  {answer.answerText ||
                    "Người yêu cầu chưa cung cấp câu trả lời."}
                </p>
              </div>
            ))
          ) : (
            <Notice>
              Không có câu hỏi xác minh trong yêu cầu này. Hãy đối chiếu trực
              tiếp trước khi bàn giao đồ.
            </Notice>
          )}
          {data.decisionNote && (
            <Notice tone={data.status === "rejected" ? "warning" : "info"}>
              <strong>Ghi chú từ người giữ</strong>
              <p className="preserve-lines">{data.decisionNote}</p>
            </Notice>
          )}
          {reviewer && data.status === "pending" && !data.stale && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (confirmed) void decide("approved");
              }}
            >
              <label>
                Ghi chú cho người yêu cầu{" "}
                <span className="field-hint">(không bắt buộc)</span>
                <textarea
                  rows={3}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  maxLength={2000}
                />
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  required
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                Tôi đã đối chiếu câu trả lời với món đồ thực tế đang giữ.
              </label>
              <ErrorNotice error={action.error} />
              <div className="form-actions">
                <button
                  type="button"
                  className="button button-secondary danger-text"
                  disabled={action.busy}
                  onClick={() => void decide("rejected")}
                >
                  Từ chối yêu cầu
                </button>
                <button className="button" disabled={action.busy || !confirmed}>
                  <Icon name="check" size={17} />
                  {action.busy ? "Đang lưu…" : "Chấp thuận & mở hội thoại"}
                </button>
              </div>
            </form>
          )}
          {!reviewer && data.status === "pending" && !data.stale && (
            <Notice>
              <strong>Đã gửi yêu cầu. Đang chờ người giữ đối chiếu.</strong>
              <p>Bạn có thể quay lại trang này để kiểm tra kết quả.</p>
            </Notice>
          )}
          {data.conversationId && (
            <a
              className="button button-wide"
              href={`/messages?conversation=${data.conversationId}`}
            >
              <Icon name="chat" size={18} />
              Mở hội thoại trao trả
              <Icon name="arrow" size={17} />
            </a>
          )}
          {data.decidedAt && (
            <p className="field-hint">
              Cập nhật lúc {formatDate(data.decidedAt, true)}
            </p>
          )}
        </section>
      </div>
    </>
  );
}

export function MyPosts() {
  const query = new URLSearchParams(window.location.search);
  const page = pageNumber(query.get("page"));
  const managed = query.get("scope") === "managed";
  const items = useResource<Page<Item>>(
    `/api/items?scope=${managed ? "managed" : "mine"}&page=${page}&pageSize=10`,
  );
  const action = useAction();
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const [deleteTarget, setDeleteTarget] = useState<Item | null>(null);
  useEffect(() => {
    if (deleteTarget && !deleteDialog.current?.open) deleteDialog.current?.showModal();
  }, [deleteTarget]);

  async function publication(item: Item) {
    const result = await action.run(() =>
      write<Item>(
        `/api/items/${item.id}/publication`,
        {
          rowVersion: item.rowVersion,
          state: item.publicationState === "published" ? "hidden" : "published",
        },
        "PUT",
      ),
    );
    if (result) items.reload();
  }
  async function deletePost(item: Item) {
    const deleted = await action.run(async () => {
      await write<void>(
        `/api/items/${item.id}`,
        { rowVersion: item.rowVersion },
        "DELETE",
      );
      return true;
    });
    if (deleted) {
      if (page > 1 && items.data?.items.length === 1) {
        query.set("page", String(page - 1));
        window.location.assign(`${window.location.pathname}?${query}`);
      } else items.reload();
    }
  }
  return (
    <>
      <PageHeader
        eyebrow="Cảm ơn bạn đã giữ gìn và sẻ chia"
        title={managed ? "Đồ đang quản lý" : "Bài đăng của tôi"}
        action={
          <a className="button" href="/post">
            <Icon name="plus" size={17} />
            Đăng tin mới
          </a>
        }
      >
        Quản lý thông tin, duyệt ảnh và kết nối người đang tìm lại món đồ.
      </PageHeader>
      <nav className="posts-nav" aria-label="Điều hướng bài đăng">
        <a
          className="button button-secondary"
          href="/posts"
          aria-current={!managed ? "page" : undefined}
        >
          Bài đăng của tôi
        </a>
        <a
          className="button button-secondary"
          href="/posts?scope=managed"
          aria-current={managed ? "page" : undefined}
        >
          Đồ đang quản lý
        </a>
        <a className="button button-secondary" href="/intakes">
          Theo dõi tiếp nhận
          <Icon name="arrow" size={16} />
        </a>
      </nav>
      {managed && <Notice>Thao tác tại Hub cần quyền tiếp nhận hoặc trao trả tương ứng được cấp cho tài khoản của bạn.</Notice>}
      <div className="posts-layout">
        <section>
          <ErrorNotice error={items.error} retry={items.reload} />
          <ErrorNotice error={action.error} retry={items.reload} />
          {items.loading && <Loading />}
          {items.data && (
            <>
              {items.data.items.length ? (
                <div className="posts-list">
                  {items.data.items.map((item) => (
                    <article className="panel managed-item" key={item.id}>
                      <div className="managed-item-top">
                        <span className="eyebrow">
                          #{item.id.slice(0, 8)} · {formatDate(item.createdAt)}
                        </span>
                        <Badge
                          value={
                            item.lifecycle === "returned"
                              ? "returned"
                              : item.publicationState
                          }
                        />
                      </div>
                      <div className="managed-item-body">
                        <a href={`/items/${item.id}`}>
                          <ItemPhoto item={item} />
                        </a>
                        <div>
                          <Badge value={item.custody.kind}>
                            {custodyLabels[item.custody.kind]}
                          </Badge>
                          <h2>
                            <a href={`/items/${item.id}`}>{item.title}</a>
                          </h2>
                          <p className="item-location">
                            <Icon name="pin" size={16} />
                            {item.foundArea}
                          </p>
                          {item.custody.kind === "point" && (
                            <p className="muted">
                              Đang được bảo quản tại{" "}
                              {item.custody.name ??
                                item.custody.displayName ??
                                "Findie Hub"}
                              .
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="card-actions">
                        {item.lifecycle === "active" &&
                          (item.custody.kind !== "point" || managed) && (
                            <>
                              <a
                                className="button button-secondary"
                                href={`/items/${item.id}/edit`}
                              >
                                Chỉnh sửa tin
                              </a>
                              <a
                                className="button button-secondary"
                                href={`/items/${item.id}/review`}
                              >
                                <Icon name="eye" size={16} />
                                {item.images.length
                                  ? "Duyệt ảnh"
                                  : "Thêm & duyệt ảnh"}
                              </a>
                              {item.custody.kind === "person" && (
                                <>
                                  <a
                                    className="button button-secondary"
                                    href={`/requests?itemId=${item.id}`}
                                  >
                                    <Icon name="document" size={16} />
                                    Xem yêu cầu
                                  </a>
                                  <a
                                    className="text-button"
                                    href={`/items/${item.id}/transfer`}
                                  >
                                    <Icon name="building" size={16} />
                                    Gửi vào Hub
                                  </a>
                                </>
                              )}
                              {item.custody.kind !== "person" && <a
                                className="button button-secondary"
                                href={`/items/${item.id}/return`}
                              >Xác nhận trao trả</a>}
                              {item.custody.kind !== "person" && <a
                                className="text-button"
                                href={`/items/${item.id}/transfer`}
                              >Chuyển vào Hub</a>}
                              {(item.publicationState === "published" ||
                                item.images.length > 0) && (
                                <button
                                  className="text-button"
                                  type="button"
                                  disabled={action.busy}
                                  onClick={() => void publication(item)}
                                >
                                  {item.publicationState === "published"
                                    ? "Ẩn tin"
                                    : "Công khai tin"}
                                </button>
                              )}
                            </>
                          )}
                        {item.canDelete && (
                          <button
                            className="text-button danger-text"
                            type="button"
                            disabled={action.busy}
                            onClick={() => setDeleteTarget(item)}
                          >
                            Xóa bài đăng
                          </button>
                        )}
                        <a className="text-button" href={`/items/${item.id}`}>
                          Xem chi tiết
                          <Icon name="arrow" size={15} />
                        </a>
                        <a className="text-button" href={`/items/${item.id}/history`}>Lịch sử bàn giao<Icon name="clock" size={15} /></a>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <EmptyState title="Chưa có bài đăng nào">
                  <p>
                    Nhặt được một món đồ? Đăng tin để giúp món đồ tìm về đúng
                    chủ.
                  </p>
                  <a className="button" href="/post">
                    Đăng tin nhặt được
                    <Icon name="plus" size={17} />
                  </a>
                </EmptyState>
              )}
              <Pagination page={items.data.page} totalPages={items.data.totalPages} />
            </>
          )}
        </section>
        <aside>
          <section className="panel hub-help">
            <span className="empty-icon">
              <Icon name="building" size={28} />
            </span>
            <p className="eyebrow">Có Findie Hub đồng hành</p>
            <h2>Bận rộn và chưa tiện tự trao trả?</h2>
            <p>
              Gửi đề nghị bàn giao món đồ vào một điểm tiếp nhận. Nhân viên sẽ
              xác nhận khi nhận món đồ thực tế tại quầy.
            </p>
            <a className="button button-secondary" href="/hubs">
              Tìm điểm tiếp nhận
              <Icon name="arrow" size={16} />
            </a>
          </section>
          <SafetyNote />
        </aside>
      </div>
      <dialog
        ref={deleteDialog}
        className="confirm-dialog"
        aria-labelledby="delete-post-title"
        aria-describedby="delete-post-warning"
        onClose={() => setDeleteTarget(null)}
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!deleteTarget || action.busy) return;
            deleteDialog.current?.close();
            void deletePost(deleteTarget);
          }}
        >
          <h2 id="delete-post-title">Xóa bài đăng “{deleteTarget?.title}”?</h2>
          <p id="delete-post-warning">
            Không thể khôi phục bài đăng sau khi xóa. Lịch sử yêu cầu nhận đồ,
            hội thoại và bàn giao vẫn được lưu giữ.
          </p>
          <div className="form-actions">
            <button className="button button-secondary" type="button" onClick={() => deleteDialog.current?.close()}>
              Hủy
            </button>
            <button className="button button-secondary danger-text" type="submit">
              Xác nhận xóa bài đăng
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}

export function TransferItem({ id }: { id: string }) {
  const item = useResource<Item>(`/api/items/${id}`);
  const points = useResource<Point[]>("/api/reception-points");
  const [selected, setSelected] = useState("");
  const [result, setResult] = useState<Intake | null>(null);
  const action = useAction();
  if (item.loading || points.loading) return <Loading />;
  if (item.error || points.error)
    return (
      <ErrorNotice
        error={item.error ?? points.error}
        retry={() => {
          item.reload();
          points.reload();
        }}
      />
    );
  if (!item.data || !points.data) return null;
  const availablePoints = points.data.filter((point) => point.id !== item.data!.custody.pointId);
  return (
    <>
      <PageHeader
        eyebrow="Thêm một nơi an tâm giữ hộ"
        title="Gửi đồ vào điểm tiếp nhận Findie Hub"
      >
        Chọn điểm tiếp nhận, gửi đề nghị rồi mang món đồ đến bàn giao tại quầy.
      </PageHeader>
      <Notice tone="warning">
        <strong>Nơi giữ chỉ thay đổi khi Hub xác nhận đã nhận đồ.</strong>
        <p>
          Gửi đề nghị không thay thế việc bàn giao thực tế. Hãy bảo quản món đồ
            tại nơi giữ hiện tại trong thời gian chờ tiếp nhận.
        </p>
      </Notice>
      <ItemSummary item={item.data} />
      {result ? (
        <section className="panel saved-panel">
          <span className="empty-icon">
            <Icon name="check" size={30} />
          </span>
          <h2>Đã gửi đề nghị tiếp nhận</h2>
          <Badge value={result.status} />
          <p>
            Mang món đồ đến{" "}
            {points.data.find((point) => point.id === selected)?.name} để nhân
            viên kiểm tra và xác nhận.
          </p>
          <a className="button" href="/posts">
            Về bài đăng của tôi
            <Icon name="arrow" size={17} />
          </a>
          <a className="text-button" href={`/intakes/${result.id}`}>Theo dõi đề nghị tiếp nhận<Icon name="arrow" size={16} /></a>
        </section>
      ) : (
        <form
          className="transfer-layout"
          onSubmit={async (event) => {
            event.preventDefault();
            const value = await action.run(() =>
              write<Intake>(`/api/items/${id}/intake-requests`, {
                targetPointId: selected,
                rowVersion: item.data!.rowVersion,
              }),
            );
            if (value) setResult(value);
          }}
        >
          <section className="panel">
            <div className="panel-title">
              <h2>Chọn điểm tiếp nhận</h2>
              <Icon name="building" size={23} />
            </div>
            {availablePoints.length ? (
              availablePoints.map((point) => (
                <label
                  className={`choice-card point-choice${selected === point.id ? " selected" : ""}`}
                  key={point.id}
                >
                  <input
                    type="radio"
                    name="point"
                    required
                    value={point.id}
                    checked={selected === point.id}
                    onChange={() => setSelected(point.id)}
                  />
                  <span>
                    <strong>{point.name}</strong>
                    <small>{point.publicAddress}</small>
                    {point.directions && <small>{point.directions}</small>}
                  </span>
                </label>
              ))
            ) : (
              <EmptyState title="Chưa có điểm tiếp nhận">
                <p>
                  Vui lòng quay lại sau. Bạn vẫn có thể tự giữ và trao trả món
                  đồ.
                </p>
              </EmptyState>
            )}
          </section>
          <aside className="panel">
            <p className="eyebrow">Tại quầy tiếp nhận</p>
            <h2>Ba bước bàn giao</h2>
            <ol className="timeline">
              <li>
                <strong>Mang theo món đồ</strong>
                <p>Xuất trình bài đăng để nhân viên tìm hồ sơ.</p>
              </li>
              <li>
                <strong>Đối chiếu tình trạng</strong>
                <p>Nhân viên kiểm tra món đồ và nơi giữ hiện tại.</p>
              </li>
              <li>
                <strong>Xác nhận đã tiếp nhận</strong>
                <p>
                  Sau khi nhận thực tế, hệ thống mới ghi nhận Hub là nơi giữ.
                </p>
              </li>
            </ol>
            <ErrorNotice error={action.error} retry={item.reload} />
            <button
              className="button button-wide"
              disabled={
                !selected ||
                action.busy ||
                item.data.lifecycle !== "active"
              }
            >
              {action.busy ? "Đang gửi đề nghị…" : "Gửi đề nghị tiếp nhận"}
              <Icon name="send" size={17} />
            </button>
            <a className="text-button" href="/posts">
              Quay lại bài đăng
            </a>
          </aside>
        </form>
      )}
    </>
  );
}

export function Messages({ user }: { user: UserProfile }) {
  const query = new URLSearchParams(window.location.search);
  const page = pageNumber(query.get("page"));
  const conversations = useResource<Page<Conversation>>(
    `/api/conversations?page=${page}&pageSize=15`,
  );
  const selectedId =
    query.get("conversation") || conversations.data?.items[0]?.id;
  const conversation = useResource<Conversation>(
    selectedId ? `/api/conversations/${encodeURIComponent(selectedId)}` : null,
  );
  return (
    <>
      <PageHeader eyebrow="Kết nối sau khi xác minh" title="Tin nhắn trao trả">
        Thống nhất thời gian và địa điểm gặp để món đồ về lại đúng chủ.
      </PageHeader>
      <div className="messenger">
        <aside className="conversation-list">
          <div className="panel-title">
            <h2>Hội thoại của bạn</h2>
            <Icon name="chat" size={21} />
          </div>
          <ErrorNotice
            error={conversations.error}
            retry={conversations.reload}
          />
          {conversations.loading && <Loading />}
          {conversations.data?.items.map((chat) => (
            <a
              key={chat.id}
              className={`conversation-link${chat.id === selectedId ? " selected" : ""}`}
              href={`/messages?conversation=${chat.id}&page=${page}`}
              aria-current={chat.id === selectedId ? "page" : undefined}
            >
              <span className="avatar">
                <Icon name="chat" size={19} />
              </span>
              <div>
                <strong>Món đồ #{chat.itemId.slice(0, 8)}</strong>
                <small>
                  {chat.canSend ? "Đang hẹn trao trả" : "Hội thoại chỉ đọc"}
                </small>
              </div>
              <Icon name="arrow" size={15} />
            </a>
          ))}
          {conversations.data && !conversations.data.items.length && (
            <p className="conversation-empty">
              Chat sẽ xuất hiện khi yêu cầu nhận đồ được chấp thuận.
            </p>
          )}
          {conversations.data && (
            <Pagination page={conversations.data.page} totalPages={conversations.data.totalPages} />
          )}
        </aside>
        <section className="conversation-main">
          <ErrorNotice error={conversation.error} retry={conversation.reload} />
          {conversation.data ? (
            <MessageThread
              key={conversation.data.id}
              chat={conversation.data}
              user={user}
              onRefresh={conversation.reload}
            />
          ) : conversation.loading ? (
            <Loading />
          ) : (
            !conversation.error && (
              <EmptyState title="Mỗi hội thoại, một cơ hội tìm lại" icon="chat">
                <p>
                  Chọn hội thoại để trao đổi. Chỉ những yêu cầu đã được chấp
                  thuận mới mở chat.
                </p>
                <a className="button button-secondary" href="/requests">
                  Xem yêu cầu trao trả
                </a>
              </EmptyState>
            )
          )}
        </section>
      </div>
    </>
  );
}

function MessageThread({
  chat,
  user,
  onRefresh,
}: {
  chat: Conversation;
  user: UserProfile;
  onRefresh: () => void;
}) {
  const item = useResource<Item>(`/api/items/${chat.itemId}`);
  const [after, setAfter] = useState(0);
  // shortcut: refresh messages on demand; add polling or push when live updates are needed.
  const incoming = useResource<MessagePage>(
    `/api/conversations/${chat.id}/messages?after=${after}&limit=50`,
  );
  const [messages, setMessages] = useState<Message[]>([]);
  const history = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState("");
  const pending = useRef<{ body: string; id: string } | null>(null);
  const action = useAction();
  useEffect(() => {
    history.current?.scrollTo(0, history.current.scrollHeight);
  }, [messages.length]);
  useEffect(() => {
    if (incoming.data)
      setMessages((previous) =>
        [
          ...new Map(
            [...previous, ...incoming.data!.items].map((message) => [
              message.id,
              message,
            ]),
          ).values(),
        ].sort((a, b) => a.sequence - b.sequence),
      );
  }, [incoming.data]);
  async function send(event: FormEvent) {
    event.preventDefault();
    const body = draft.trim();
    if (!body || !chat.canSend) return;
    if (pending.current?.body !== body)
      pending.current = { body, id: crypto.randomUUID() };
    const sent = await action.run(() =>
      write<Message>(`/api/conversations/${chat.id}/messages`, {
        body,
        clientMessageId: pending.current!.id,
      }),
    );
    if (sent) {
      setMessages((previous) =>
        [
          ...new Map(
            [...previous, sent].map((message) => [message.id, message]),
          ).values(),
        ].sort((a, b) => a.sequence - b.sequence),
      );
      setDraft("");
      pending.current = null;
      incoming.reload();
    }
  }
  return (
    <>
      <div className="chat-heading">
        <div>
          <h2>{item.data?.title ?? `Món đồ #${chat.itemId.slice(0, 8)}`}</h2>
          <span className="muted">
            {chat.canSend ? "Yêu cầu đã được chấp thuận" : "Hội thoại chỉ đọc"}
          </span>
        </div>
        <button
          className="icon-button"
          aria-label="Cập nhật hội thoại"
          type="button"
          onClick={() => {
            incoming.reload();
            item.reload();
            onRefresh();
          }}
        >
          <Icon name="refresh" size={19} />
        </button>
      </div>
      <div className="chat-notice">
        <Icon name="shield" size={18} />
        <p>
          Hẹn gặp tại nơi công cộng. Không chuyển tiền trước khi nhận được món
          đồ.
        </p>
      </div>
      <div
        className="message-history"
        ref={history}
        aria-label="Nội dung hội thoại"
        aria-live="polite"
      >
        <ErrorNotice error={incoming.error} retry={incoming.reload} />
        {!messages.length && incoming.loading && <Loading />}
        {!messages.length && !incoming.loading && !incoming.error && (
          <div className="chat-welcome">
            <Icon name="chat" size={32} />
            <h3>Bắt đầu bằng một lời chào.</h3>
            <p>Cùng chọn một nơi công cộng thuận tiện để trao trả món đồ.</p>
          </div>
        )}
        {messages.map((message) => (
          <article
            key={message.id}
            className={`message${message.senderUserId === user.id ? " message-mine" : ""}`}
          >
            <span className="message-sender">
              {message.senderUserId === user.id ? "Bạn" : "Người trao đổi"}
            </span>
            <p>{message.body}</p>
            <time dateTime={message.createdAt}>
              {formatDate(message.createdAt, true)}
            </time>
          </article>
        ))}
        {incoming.data?.hasMore && (
          <button
            className="button button-secondary load-messages"
            type="button"
            disabled={incoming.loading}
            onClick={() => setAfter(incoming.data!.nextAfter)}
          >
            Tải tin nhắn tiếp theo
            <Icon name="arrow" size={15} />
          </button>
        )}
      </div>
      {!chat.canSend && (
        <Notice>
          Món đồ đã đổi nơi giữ, đã trao trả hoặc bài đăng đã bị xóa. Bạn có thể
          đọc lại lịch sử hội thoại.
        </Notice>
      )}
      <form className="message-composer" onSubmit={(event) => void send(event)}>
        <ErrorNotice error={action.error} />
        <label className="sr-only" htmlFor="message-body">
          Nội dung tin nhắn
        </label>
        <div>
          <textarea
            id="message-body"
            placeholder={
              chat.canSend
                ? "Nhập lời nhắn để hẹn trao trả…"
                : "Hội thoại chỉ đọc"
            }
            rows={2}
            maxLength={4000}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            disabled={!chat.canSend || action.busy}
          />
          <button
            className="button"
            disabled={!chat.canSend || !draft.trim() || action.busy}
            type="submit"
          >
            {action.busy ? "Đang gửi…" : "Gửi"}
            <Icon name="send" size={17} />
          </button>
        </div>
      </form>
      {chat.reviewerUserId === user.id && chat.canSend && item.data && (
        <div className="handover-action">
          <ConfirmDialog
            trigger={
              <>
                <Icon name="check" size={17} />
                Xác nhận đã trao trả
              </>
            }
            title="Bạn đã trao tận tay món đồ?"
            busy={action.busy}
            onConfirm={async () => {
              const result = await action.run(() =>
                write<{ id: string }>(`/api/items/${chat.itemId}/return`, {
                  rowVersion: item.data!.rowVersion,
                  confirmedPhysicalHandover: true,
                  claimId: chat.id,
                }),
              );
              if (result) {
                onRefresh();
                return true;
              }
              return false;
            }}
          >
            <p>
              Chỉ xác nhận khi người nhận đã đối chiếu và nhận món đồ thực tế.
              Hội thoại sẽ chuyển sang chỉ đọc.
            </p>
            <ErrorNotice error={action.error} />
          </ConfirmDialog>
        </div>
      )}
    </>
  );
}
