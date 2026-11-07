import { useState } from "react";
import { formatDate, pageNumber, write, type CustodyEvent, type Item, type Page } from "../lib/api";
import { directReturnInput } from "../lib/itemForm";
import { useAction, useResource } from "../hooks/hooks";
import { Badge, EmptyState, ErrorNotice, Icon, ItemSummary, Loading, Notice, PageHeader, Pagination, SafetyNote } from "../components/ui";

export function CustodyHistory({ id }: { id: string }) {
  const page = pageNumber(new URLSearchParams(window.location.search).get("page"));
  const events = useResource<Page<CustodyEvent>>(`/api/items/${id}/custody-events?page=${page}&pageSize=20`);
  const labels: Record<string, string> = { registered: "Đăng ký món đồ", received: "Hub đã tiếp nhận", returned: "Đã trao trả cho chủ sở hữu" };
  return <>
    <PageHeader eyebrow={`Món đồ #${id.slice(0, 8)}`} title="Lịch sử bàn giao">
      Lịch sử dành cho người đăng và người có quyền quản lý món đồ.
    </PageHeader>
    <ErrorNotice error={events.error} retry={events.reload} />
    {events.loading && <Loading />}
    {events.data && <section className="panel">
      {events.data.items.length ? <ol className="timeline">
        {events.data.items.map((event) => <li key={event.id}>
          <strong>{labels[event.eventKind] ?? event.eventKind}</strong>
          <p><time dateTime={event.occurredAt}>{formatDate(event.occurredAt, true)}</time> · Lần giữ đồ {event.custodyVersion}</p>
        </li>)}
      </ol> : <EmptyState title="Chưa có lịch sử bàn giao"><p>Các lần tiếp nhận và trao trả sẽ hiển thị tại đây.</p></EmptyState>}
      <Pagination page={events.data.page} totalPages={events.data.totalPages} />
    </section>}
    <a className="text-button" href="/posts"><Icon name="back" size={16} />Về bài đăng của tôi</a>
  </>;
}

export function ReturnItem({ id }: { id: string }) {
  const item = useResource<Item>(`/api/items/${id}`);
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState<CustodyEvent | null>(null);
  const action = useAction();
  if (item.loading) return <Loading />;
  if (item.error || !item.data) return <ErrorNotice error={item.error} retry={item.reload} />;
  const data = item.data;
  return <>
    <PageHeader eyebrow="Đối chiếu trước khi bàn giao" title="Xác nhận trao trả món đồ">
      Người giữ hoặc nhân viên có quyền trao trả xác nhận sau khi chủ sở hữu đã nhận đồ thực tế.
    </PageHeader>
    <ItemSummary item={data} />
    {result || data.lifecycle === "returned" ? <section className="panel saved-panel">
      <Badge value="returned" />
      <h2>Đã ghi nhận trao trả</h2>
      <a className="button" href={`/items/${id}/history`}>Xem lịch sử bàn giao<Icon name="arrow" size={17} /></a>
    </section> : data.custody.kind === "person" ? <Notice>
      Việc trao trả đồ cá nhân cần một yêu cầu nhận đồ đã được chấp thuận.
      <p><a href={`/requests?itemId=${id}`}>Mở yêu cầu nhận đồ để tiếp tục qua hội thoại.</a></p>
    </Notice> : <form className="panel claim-form form-stack" onSubmit={async (event) => {
      event.preventDefault();
      const value = await action.run(() => write<CustodyEvent>(`/api/items/${id}/return`,
        directReturnInput(data.custody.kind, data.rowVersion, note, confirmed)));
      if (value) setResult(value);
    }}>
      <SafetyNote />
      <label>Ghi chú xác minh {data.custody.kind === "point" ? "(bắt buộc tại Hub)" : "(không bắt buộc)"}
        <textarea rows={4} value={note} maxLength={2000} required={data.custody.kind === "point"}
          disabled={action.busy} onChange={(event) => setNote(event.target.value)} />
      </label>
      <label className="checkbox-field"><input type="checkbox" required checked={confirmed}
        disabled={action.busy} onChange={(event) => setConfirmed(event.target.checked)} />
        Tôi đã đối chiếu chủ sở hữu và bàn giao món đồ thực tế.
      </label>
      <ErrorNotice error={action.error} retry={item.reload} />
      <div className="form-actions"><button className="button" disabled={action.busy || !confirmed}>
        {action.busy ? "Đang xác nhận…" : "Xác nhận đã trao trả"}<Icon name="check" size={17} />
      </button></div>
    </form>}
  </>;
}
