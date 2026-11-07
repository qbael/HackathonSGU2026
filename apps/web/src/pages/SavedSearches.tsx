import { useAction, useResource } from "../hooks/hooks";
import { formatDate, write } from "../lib/api";
import type { SavedSearch } from "../lib/search";
import { EmptyState, ErrorNotice, Icon, Loading, Notice, PageHeader } from "../components/ui";

export default function SavedSearches({ searches }: {
  searches: ReturnType<typeof useResource<SavedSearch[]>>;
}) {
  const action = useAction();
  return (
    <>
      <PageHeader title="Tin tìm đang theo dõi" eyebrow="Thêm cơ hội tìm lại"
        action={<a className="button button-secondary" href="/search"><Icon name="search" size={16} />Tìm kiếm</a>}>
        Findie kiểm tra định kỳ và thông báo khi có món đồ có thể phù hợp. Gợi ý không xác nhận quyền sở hữu.
      </PageHeader>
      <ErrorNotice error={searches.error} retry={searches.reload} />
      <ErrorNotice error={action.error} />
      {searches.loading && <Loading />}
      {searches.data && (searches.data.length ? (
        <div className="requests-list">
          {searches.data.map((search) => (
            <article className="panel request-card" key={search.id}>
              <div className="request-card-top">
                <span className="eyebrow">Lưu ngày {formatDate(search.createdAt, true)}</span>
                <button className="text-button" type="button" disabled={action.busy}
                  onClick={() => void action.run(async () => {
                    await write<void>(`/api/saved-searches/${search.id}`, {}, "DELETE");
                    searches.reload();
                  })}>
                  <Icon name="close" size={16} />Dừng theo dõi
                </button>
              </div>
              <h2>{search.text || `Tìm theo ${search.imageCount} ảnh món đồ`}</h2>
              {search.imageCount > 0 && <p>Đối chiếu theo {search.imageCount} ảnh. Ảnh gốc không được lưu.</p>}
              {search.area && <p><Icon name="pin" size={16} /> Khu vực ưu tiên: {search.area}</p>}
              {(search.from || search.until) && <p>Ngày nhặt: {search.from ? formatDate(search.from) : "Không giới hạn"} – {search.until ? formatDate(search.until) : "Không giới hạn"}</p>}
              {search.lostAt && <p>Thời điểm mất: {formatDate(search.lostAt, true)}</p>}
              <p className="muted">{search.lastCheckedAt
                ? `Kiểm tra gần nhất: ${formatDate(search.lastCheckedAt, true)}`
                : "Đang chờ lượt kiểm tra đầu tiên."}</p>
              {search.needsRefresh && <Notice tone="warning">
                <p>Cần cập nhật tin tìm để tiếp tục đối chiếu. Hãy tìm kiếm lại với ảnh hoặc mô tả rồi lưu tin mới.</p>
                <a href="/search">Tìm kiếm lại</a>
              </Notice>}
              {search.matches.length ? search.matches.map((match) => (
                <section className="panel" key={match.itemId} aria-label={`Thông báo về ${match.title}`}>
                  <p className="eyebrow">{match.readAt ? "Đã đọc" : "Thông báo mới"} · {formatDate(match.createdAt, true)}</p>
                  <h3><a href={`/items/${match.itemId}`}>{match.title}</a></h3>
                  <p>{match.foundArea}</p>
                  <div className="card-actions">
                    <a className="button button-secondary" href={`/items/${match.itemId}`}>Xem món đồ<Icon name="arrow" size={16} /></a>
                    {!match.readAt && <button className="text-button" type="button" disabled={action.busy}
                      onClick={() => void action.run(async () => {
                        await write<void>(`/api/saved-searches/${search.id}/matches/${match.itemId}/read`, {}, "PUT");
                        searches.reload();
                      })}>Đánh dấu đã đọc</button>}
                  </div>
                </section>
              )) : <p>Chưa có thông báo phù hợp. Findie sẽ tiếp tục kiểm tra định kỳ.</p>}
            </article>
          ))}
        </div>
      ) : <EmptyState title="Bạn chưa theo dõi tin tìm nào" icon="search">
        <p>Sau khi tìm kiếm, chọn “Theo dõi tìm kiếm này” để lưu mô tả và ảnh dùng đối chiếu.</p>
        <a className="button" href="/search">Tìm đồ thất lạc</a>
      </EmptyState>)}
    </>
  );
}
