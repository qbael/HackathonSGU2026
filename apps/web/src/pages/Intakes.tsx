import { useState } from "react";
import { ApiError, formatDate, pageNumber, write, type Intake, type Item, type Page, type Point } from "../lib/api";
import type { UserProfile } from "../lib/auth";
import { useAction, useResource } from "../hooks/hooks";
import { intakeDecision } from "../lib/intakeDecision";
import { Badge, EmptyState, ErrorNotice, Icon, ItemSummary, Loading, Notice, PageHeader, Pagination } from "../components/ui";

export function Intakes({ user }: { user: UserProfile }) {
  const query = new URLSearchParams(window.location.search);
  const page = pageNumber(query.get("page"));
  const pointId = query.get("pointId") ?? "";
  const filter = new URLSearchParams({ page: String(page), pageSize: "10" });
  if (pointId) filter.set("pointId", pointId);
  const intakes = useResource<Page<Intake>>(`/api/intake-requests?${filter}`);
  const points = useResource<Point[]>("/api/reception-points");
  return (
    <>
      <PageHeader eyebrow="Bàn giao tại Findie Hub" title="Đề nghị tiếp nhận" action={
        <button className="button button-secondary" onClick={intakes.reload} disabled={intakes.loading}>
          <Icon name="refresh" size={17} /> Cập nhật
        </button>
      }>
        Theo dõi đề nghị của bạn và tiếp nhận món đồ tại Hub bạn được cấp quyền.
      </PageHeader>
      <div className="form-stack">
      <form className="panel" action="/intakes" method="get">
        <label>
          Điểm tiếp nhận
          <select name="pointId" defaultValue={pointId}>
            <option value="">Tất cả điểm tiếp nhận</option>
            {pointId && !points.data?.some((point) => point.id === pointId) && (
              <option value={pointId}>Điểm #{pointId.slice(0, 8)}</option>
            )}
            {points.data?.map((point) => <option key={point.id} value={point.id}>{point.name}</option>)}
          </select>
        </label>
        <div className="form-actions">
          <button className="button button-secondary">Lọc đề nghị</button>
        </div>
        <ErrorNotice error={points.error} retry={points.reload} />
      </form>
      <ErrorNotice error={intakes.error} retry={intakes.reload} />
      {intakes.loading && <Loading />}
      {intakes.data && <>
        {intakes.data.items.length ? (
          <div className="requests-list">
            {intakes.data.items.map((intake) => (
              <article className="panel request-card" key={intake.id}>
                <div className="request-card-top">
                  <span className="eyebrow">
                    {intake.requestedBy === user.id ? "Đề nghị của bạn" : "Đề nghị gửi đến Hub"} · {formatDate(intake.createdAt, true)}
                  </span>
                  <Badge value={intake.status} />
                </div>
                <h2>Món đồ #{intake.itemId.slice(0, 8)}</h2>
                <p className="muted">
                  <Icon name="building" size={17} /> {points.data?.find((point) => point.id === intake.targetPointId)?.name ?? `Điểm #${intake.targetPointId.slice(0, 8)}`}
                </p>
                {intake.stale && <Notice tone="warning">Nơi giữ hoặc trạng thái món đồ đã thay đổi, hoặc bài đăng đã bị xóa. Đề nghị này chỉ dùng để tra cứu.</Notice>}
                {intake.decisionNote && <p className="preserve-lines">{intake.decisionNote}</p>}
                <div className="card-actions">
                  <a className="button button-secondary" href={`/intakes/${intake.id}`}>
                    Xem đề nghị <Icon name="arrow" size={16} />
                  </a>
                  <a className="text-button" href={`/items/${intake.itemId}`}>Xem món đồ</a>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="Chưa có đề nghị tiếp nhận" icon="document">
            <p>{pointId ? "Không có đề nghị tại điểm tiếp nhận đã chọn." : "Đề nghị bạn gửi hoặc được phân quyền tiếp nhận tại Hub sẽ hiện ở đây."}</p>
            <a className="button" href="/posts">Xem bài đăng của tôi <Icon name="arrow" size={17} /></a>
          </EmptyState>
        )}
        <Pagination page={intakes.data.page} totalPages={intakes.data.totalPages} />
      </>}
      </div>
    </>
  );
}

export function IntakeDetail({ id, user }: { id: string; user: UserProfile }) {
  const intake = useResource<Intake>(`/api/intake-requests/${id}`);
  const item = useResource<Item>(intake.data ? `/api/items/${intake.data.itemId}` : null);
  const point = useResource<Point>(intake.data ? `/api/reception-points/${intake.data.targetPointId}` : null);
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const action = useAction();
  function refresh() {
    action.setError(null);
    setConfirmed(false);
    intake.reload();
    item.reload();
  }
  async function decide(decision: "received" | "rejected") {
    if (intake.loading || intake.error || !intake.data) return;
    const result = await action.run(() => write<Intake>(`/api/intake-requests/${id}/decision`,
      intakeDecision(intake.data!, decision, confirmed, note)));
    if (result) {
      setNote("");
      refresh();
    }
  }
  if (intake.loading) return <Loading />;
  if (!intake.data) {
    if (intake.error instanceof ApiError && intake.error.status === 404) {
      return (
        <EmptyState title="Yêu cầu tiếp nhận không tồn tại" icon="document">
          <p>Yêu cầu tiếp nhận này không tồn tại hoặc đã được xử lý/gỡ bỏ.</p>
          <a className="button" href="/intakes">
            Về danh sách tiếp nhận
          </a>
        </EmptyState>
      );
    }
    return <ErrorNotice error={intake.error} retry={intake.reload} />;
  }
  const data = intake.data;
  const own = data.requestedBy === user.id;
  const isStaffForThisPoint = Boolean(
    (user.isStaff && user.managedPoints?.some((p) => p.id === data.targetPointId)) ||
    user.isAdmin
  );
  const canDecide = isStaffForThisPoint && !intake.error && Number.isSafeInteger(data.itemRowVersion) && data.itemRowVersion > 0;
  const decisionForm = (
    <form className="form-stack" onSubmit={(event) => { event.preventDefault(); if (confirmed) void decide("received"); }}>
      <Notice>
        Chỉ nhân viên được cấp quyền tiếp nhận tại Hub này có thể xử lý đề nghị. Chỉ xác nhận sau khi đã nhận món đồ thực tế.
      </Notice>
      <label>
        Ghi chú cho người gửi <span className="field-hint">(không bắt buộc)</span>
        <textarea rows={3} maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} disabled={action.busy} />
      </label>
      <label className="checkbox-field">
        <input type="checkbox" required checked={confirmed} disabled={action.busy || !canDecide} onChange={(event) => setConfirmed(event.target.checked)} />
        Tôi đã kiểm tra và nhận món đồ thực tế tại điểm tiếp nhận này.
      </label>
      <ErrorNotice error={action.error} retry={refresh} />
      <div className="form-actions">
        <button type="button" className="button button-secondary danger-text" disabled={action.busy || !canDecide} onClick={() => void decide("rejected")}>Từ chối đề nghị</button>
        <button className="button" disabled={action.busy || !canDecide || !confirmed}>
          <Icon name="check" size={17} />{action.busy ? "Đang lưu…" : "Xác nhận đã tiếp nhận"}
        </button>
      </div>
    </form>
  );
  return (
    <>
      <PageHeader eyebrow={`Đề nghị #${id.slice(0, 8)}`} title="Tiến trình tiếp nhận tại Hub" action={
        <button className="button button-secondary" type="button" onClick={refresh} disabled={action.busy}>
          <Icon name="refresh" size={17} /> Cập nhật
        </button>
      }>Gửi lúc {formatDate(data.createdAt, true)}. Hub chỉ trở thành nơi giữ sau khi nhận đồ thực tế.</PageHeader>
      <ErrorNotice error={intake.error} retry={refresh} />
      <div className="claim-layout">
        <aside className="form-sidebar">
          {item.loading && <Loading />}
          {item.data ? <ItemSummary item={item.data} /> : <a className="text-button" href={`/items/${data.itemId}`}>Món đồ #{data.itemId.slice(0, 8)} <Icon name="arrow" size={16} /></a>}
          {item.error instanceof ApiError && item.error.status === 404 ? (
            <Notice>Nội dung món đồ không còn khả dụng hoặc chưa được chia sẻ. Chỉ đối chiếu món đồ thực tế và mã đề nghị tại quầy khi đề nghị còn hiệu lực.</Notice>
          ) : <ErrorNotice error={item.error} retry={refresh} />}
          <a className="text-button" href="/intakes"><Icon name="back" size={16} /> Tất cả đề nghị</a>
        </aside>
        <section className="panel claim-form form-stack">
          <div className="panel-title"><h2>Điểm tiếp nhận</h2><Badge value={data.status} /></div>
          <h3>{point.data?.name ?? `Điểm #${data.targetPointId.slice(0, 8)}`}</h3>
          {point.data && <>
            <p className="muted"><Icon name="pin" size={16} /> {point.data.publicAddress}</p>
            {point.data.directions && <p className="preserve-lines">{point.data.directions}</p>}
          </>}
          <ErrorNotice error={point.error} retry={point.reload} />
          {data.stale && <Notice tone="warning">Nơi giữ hoặc trạng thái món đồ đã thay đổi, hoặc bài đăng đã bị xóa. Không thể xử lý đề nghị này.</Notice>}
          {data.decisionNote && <Notice tone={data.status === "rejected" ? "warning" : "info"}>
            <strong>Ghi chú từ điểm tiếp nhận</strong><p className="preserve-lines">{data.decisionNote}</p>
          </Notice>}
          {data.status === "pending" && !data.stale && (
            <>
              {own && (
                <Notice>
                  <strong>Đang chờ Hub tiếp nhận.</strong>
                  <p>Món đồ vẫn ở nơi giữ hiện tại cho đến khi bạn mang đồ tới và nhân viên tiếp nhận tại quầy.</p>
                </Notice>
              )}
              {isStaffForThisPoint && (
                <div style={{ marginTop: "1rem" }}>
                  <h3 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.5rem" }}>
                    Bàn tiếp nhận nhân viên Hub
                  </h3>
                  {decisionForm}
                </div>
              )}
              {!own && !isStaffForThisPoint && (
                <Notice>
                  Đề nghị đang chờ nhân viên phụ trách tại trạm này kiểm tra và tiếp nhận hiện vật.
                </Notice>
              )}
            </>
          )}
          {data.status === "received" && <Notice tone="success">Đề nghị đã hoàn tất; Hub đã xác nhận nhận món đồ thực tế.</Notice>}
          {data.status === "rejected" && <Notice tone="warning">Hub đã từ chối đề nghị. Việc gửi đề nghị này không thay đổi nơi giữ món đồ.</Notice>}
          {data.decidedAt && <p className="field-hint">Cập nhật lúc {formatDate(data.decidedAt, true)}</p>}
        </section>
      </div>
    </>
  );
}
