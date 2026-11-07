import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError,
  custodyLabels,
  formatDate,
  foundTime,
  imageUrl,
  pageNumber,
  type Item,
  type Page,
  type Point,
} from "../lib/api";
import { useResource } from "../hooks/hooks";
import { SearchImages } from "../components/SearchImages";
import { vietnamLocal } from "../lib/itemForm";
import {
  basicSearchUrl,
  searchImages,
  searchText,
  type SearchFilters,
  type SearchResponse,
} from "../lib/search";
import {
  Badge,
  EmptyState,
  ErrorNotice,
  Icon,
  ItemPhoto,
  Loading,
  Notice,
  PageHeader,
  Pagination,
  SafetyNote,
} from "../components/ui";

function LostTimeInput({ defaultValue, disabled }: { defaultValue?: string; disabled?: boolean }) {
  return (
    <label className="search-lost-time">
      Thời điểm mất ước tính (không bắt buộc)
      <input
        name="lostAt"
        type="datetime-local"
        defaultValue={defaultValue}
        max={vietnamLocal(new Date().toISOString())}
        disabled={disabled}
      />
      <span className="field-hint">Giờ Việt Nam · Ưu tiên món được nhặt gần sau thời điểm này.</span>
    </label>
  );
}

export function Home({ signedIn, onImageSearch }: {
  signedIn: boolean;
  onImageSearch: (input: SearchInput) => void;
}) {
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [from, setFrom] = useState("");
  const [until, setUntil] = useState("");
  return (
    <>
      <section className="hero" aria-labelledby="home-title">
        <span className="eyebrow hero-eyebrow">
          <span className="status-dot" />
          Kết nối để tìm lại
        </span>
        <h1 id="home-title">
          Bạn đang tìm
          <br className="mobile-break" /> <span>món đồ nào?</span>
        </h1>
        <p>
          Một chút mô tả. Một cơ hội tìm lại.
          <br />
          Cùng Findie kết nối với người đang giữ món đồ của bạn.
        </p>
      </section>
      <form className="search-card" action="/search" method="get" onSubmit={(event) => {
        if (!files.length) return;
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        onImageSearch({ text: query.trim(), files, filters: {
          area: String(form.get("area") ?? "").trim() || undefined,
          from: from || undefined,
          until: until || undefined,
          lostAt: String(form.get("lostAt") ?? "") || undefined,
        } });
      }}>
        <input type="hidden" name="mode" value={query.trim() ? "text" : "basic"} />
        <div className="search-card-heading">
          <Icon name="search" />
          <h2>Tìm đồ thất lạc</h2>
          <span>Từ những chi tiết bạn còn nhớ</span>
        </div>
        <div className="search-card-body">
          {signedIn ? <SearchImages files={files} onChange={setFiles} /> : (
            <div className="search-images">
              <a className="upload-zone" href="/signin?returnUrl=%2F">
                <Icon name="upload" size={24} />
                <strong>Đăng nhập để thêm ảnh tìm kiếm</strong>
                <span>Tối đa 3 ảnh · Có thể kết hợp với mô tả</span>
              </a>
            </div>
          )}
          <div className="field-label">
            <label htmlFor="home-query">Đặc điểm món đồ</label>
            <span className="field-hint">Màu sắc, hình dáng, phụ kiện…</span>
          </div>
          <div className="textarea-wrap">
            <textarea
              id="home-query"
              name="q"
              maxLength={2000}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ví dụ: Ví da màu đen, khóa kéo vàng, có một móc khóa nhỏ…"
              rows={3}
            />
            <span className="character-count">{query.length}/2000</span>
          </div>
          <div className="suggestions">
            <span>Thử tìm</span>
            {["Ví da đen", "Chùm chìa khóa", "Balô laptop xám"].map((text) => (
              <button
                type="button"
                key={text}
                onClick={() => {
                  setQuery(text);
                  document.getElementById("home-query")?.focus();
                }}
              >
                {text}
                <Icon name="plus" size={12} />
              </button>
            ))}
          </div>
          <div className="search-context">
            <label>
              Khu vực nhặt được
              <div className="input-icon">
                <Icon name="pin" size={17} />
                <input
                  name="area"
                  placeholder="Phường, quận hoặc thành phố"
                  maxLength={200}
                />
              </div>
              <span className="field-hint">Tìm trong khu vực trước; nếu chưa đủ phù hợp sẽ tìm thêm ở nơi khác. Chỉ tìm theo khu vực: lọc chính xác.</span>
            </label>
            <label>
              Từ ngày
              <input
                type="date"
                name="from"
                value={from}
                max={until || undefined}
                onChange={(event) => setFrom(event.target.value)}
              />
            </label>
            <label>
              Đến ngày
              <input
                type="date"
                name="until"
                value={until}
                min={from || undefined}
                onChange={(event) => setUntil(event.target.value)}
              />
            </label>
            <LostTimeInput disabled={!query.trim() && files.length === 0} />
          </div>
          <div className="search-bottom">
            <button className="button" type="submit">
              <Icon name="search" size={18} />
              Tìm kiếm món đồ
              <Icon name="arrow" size={17} />
            </button>
          </div>
        </div>
      </form>
      <section className="benefits" aria-labelledby="benefits-title">
        <div className="section-heading">
          <p className="eyebrow">Tìm lại đồ, giữ trọn niềm tin</p>
          <h2 id="benefits-title">An tâm trên từng bước kết nối.</h2>
        </div>
        <div className="benefit-grid">
          {[
            [
              "shield",
              "01",
              "Bảo vệ thông tin riêng",
              "Chỉ ảnh đã qua xử lý và được duyệt mới xuất hiện trên tin công khai.",
            ],
            [
              "lock",
              "02",
              "Xác minh trước khi kết nối",
              "Người giữ đối chiếu câu trả lời của bạn trước khi mở hội thoại trao trả.",
            ],
            [
              "building",
              "03",
              "Có Findie Hub đồng hành",
              "Tìm điểm tiếp nhận để bàn giao, bảo quản và nhận lại món đồ trực tiếp.",
            ],
          ].map(([icon, number, title, description]) => (
            <article className="benefit-card" key={number}>
              <div>
                <span className={`benefit-icon benefit-${number}`}>
                  <Icon
                    name={icon as "shield" | "lock" | "building"}
                    size={24}
                  />
                </span>
                <span className="benefit-number">{number}</span>
              </div>
              <h3>{title}</h3>
              <p>{description}</p>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}

export type SearchInput = { text: string; files: readonly File[]; filters: SearchFilters };

export function Search({ initialRequest }: { initialRequest?: SearchInput | null }) {
  const query = new URLSearchParams(window.location.search);
  const page = pageNumber(query.get("page"));
  const [mode, setMode] = useState(
    query.get("mode") === "basic" ? "basic" : "text",
  );
  const [files, setFiles] = useState<readonly File[]>(initialRequest?.files ?? []);
  const [from, setFrom] = useState(initialRequest?.filters.from ?? query.get("from") ?? "");
  const [until, setUntil] = useState(initialRequest?.filters.until ?? query.get("until") ?? "");
  const [request, setRequest] = useState<SearchInput | null>(() => initialRequest ?? (
    query.get("mode") !== "basic" && query.get("q")?.trim()
      ? {
          text: query.get("q")!.trim(),
          files: [],
          filters: {
            area: query.get("area")?.trim() || undefined,
            from: query.get("from") || undefined,
            until: query.get("until") || undefined,
            lostAt: query.get("lostAt") || undefined,
          },
        }
      : null),
  );
  const [formError, setFormError] = useState<Error | null>(null);
  const [suggestions, setSuggestions] = useState<SearchResponse | null>(null);
  const [searchError, setSearchError] = useState<Error | null>(null);
  const [searching, setSearching] = useState(Boolean(request));
  const [searchStep, setSearchStep] = useState("Đang tải ảnh lên và mã hóa dữ liệu…");
  const [attempt, setAttempt] = useState(0);
  const searchControllerRef = useRef<AbortController | null>(null);

  const cancelSearch = () => {
    searchControllerRef.current?.abort();
    setSearching(false);
    setRequest(null);
  };

  const filter = new URLSearchParams({ page: String(page), pageSize: "12" });
  for (const key of ["q", "area", "from", "until"])
    if (query.get(key)?.trim()) filter.set(key, query.get(key)!.trim());
  const hasBasicFilters = ["q", "area", "from", "until"].some((key) => filter.has(key));
  const basic = useResource<Page<Item>>(request || !hasBasicFilters ? null : `/api/items?${filter}`);
  useEffect(() => {
    if (!request) return;
    const controller = new AbortController();
    searchControllerRef.current = controller;
    let active = true;
    setSearching(true);
    setSearchError(null);
    setSuggestions(null);
    setSearchStep("Đang tải ảnh lên và mã hóa dữ liệu…");

    const t1 = setTimeout(() => {
      if (active) setSearchStep("AI đang phân tích đặc trưng hình ảnh…");
    }, 1500);
    const t2 = setTimeout(() => {
      if (active) setSearchStep("Đang so khớp với cơ sở dữ liệu tìm kiếm…");
    }, 3500);

    const signal = AbortSignal.any([
      controller.signal,
      AbortSignal.timeout(request.files.length ? 960000 : 45000),
    ]);
    const result =
      request.files.length
        ? searchImages(request.files, request.text, request.filters, signal)
        : searchText(request.text, request.filters, signal);
    result
      .then((value) => {
        if (active) setSuggestions(value);
      })
      .catch((cause) => {
        if (active) {
          if (controller.signal.aborted) return;
          setSearchError(
            cause instanceof Error && !signal.aborted
              ? cause
              : new Error("Máy chủ phản hồi quá lâu. Vui lòng thử lại."),
          );
        }
      })
      .finally(() => {
        if (active) setSearching(false);
      });
    return () => {
      active = false;
      clearTimeout(t1);
      clearTimeout(t2);
      controller.abort();
    };
  }, [request, attempt]);
  function submit(event: FormEvent<HTMLFormElement>) {
    if (mode === "basic") return;
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = String(form.get("q") ?? "").trim();
    if (!text && !files.length) {
      setFormError(new Error("Hãy nhập mô tả hoặc chọn từ 1 đến 3 ảnh để tìm kiếm."));
      return;
    }
    setFormError(null);
    setRequest({
      text,
      files,
      filters: {
        area: String(form.get("area") ?? "").trim() || undefined,
        from: String(form.get("from") ?? "") || undefined,
        until: String(form.get("until") ?? "") || undefined,
        lostAt: String(form.get("lostAt") ?? "") || undefined,
      },
    });
  }
  const items = request
    ? suggestions?.items.map((hit) => hit.item)
    : basic.data?.items;
  const loading = request ? searching : basic.loading;
  const error = request ? searchError : basic.error;
  const retry = request ? () => setAttempt((value) => value + 1) : basic.reload;
  const fallback = basicSearchUrl(
    request?.filters ?? {
      area: query.get("area") ?? undefined,
      from: query.get("from") ?? undefined,
      until: query.get("until") ?? undefined,
    },
  );
  return (
    <>
      <PageHeader
        eyebrow="Có thể món đồ của bạn đang ở đây"
        title="Tìm đồ thất lạc"
      >
        Tìm bằng mô tả, tối đa 3 ảnh hoặc kết hợp cả hai. Tìm trong khu vực trước;
        nếu chưa đủ phù hợp sẽ tìm thêm ở nơi khác. Ngày nhặt được vẫn dùng để lọc.
      </PageHeader>
      <div className="search-layout">
        <aside className="panel filter-panel">
          <div className="panel-title">
            <h2>Bộ lọc tìm kiếm</h2>
            <a className="text-button" href="/search">
              Đặt lại
            </a>
          </div>
          <form action="/search" onSubmit={submit}>
            <label>
              Cách tìm kiếm
              <select
                name="mode"
                value={mode}
                onChange={(event) => setMode(event.target.value)}
              >
                <option value="text">Gợi ý theo mô tả / ảnh</option>
                <option value="basic">Bộ lọc cơ bản</option>
              </select>
            </label>
            <ErrorNotice error={formError} />
            {mode !== "basic" && <SearchImages files={files} onChange={setFiles} />}
            <label>
              {mode === "basic" ? "Từ khóa" : "Mô tả món đồ"}
              <input
                name="q"
                defaultValue={initialRequest?.text ?? query.get("q") ?? ""}
                maxLength={mode === "basic" ? 200 : 2000}
                placeholder={mode === "basic" ? "Ví, chìa khóa, balô…" : "Ví da đen tại phòng E.205…"}
              />
              {mode === "text" && (
                <span className="field-hint">
                  Có thể thêm vị trí cụ thể, như phòng E.205 hoặc sảnh hội trường
                  A. Nhập Trường Đại học Sài Gòn ở mục khu vực ưu tiên.
                </span>
              )}
            </label>
            <label>
              {mode === "basic" ? "Khu vực" : "Khu vực ưu tiên"}
              <input
                name="area"
                defaultValue={initialRequest?.filters.area ?? query.get("area") ?? ""}
                maxLength={200}
                placeholder="Ví dụ: Trường Đại học Sài Gòn"
              />
              {mode !== "basic" && <span className="field-hint">Nếu chưa có tin đủ phù hợp trong khu vực, sẽ tìm thêm ở nơi khác; tin cùng khu vực vẫn xếp trước.</span>}
            </label>
            <label>
              Nhặt từ ngày
              <input
                type="date"
                name="from"
                value={from}
                max={until || undefined}
                onChange={(event) => setFrom(event.target.value)}
              />
            </label>
            <label>
              Đến ngày
              <input
                type="date"
                name="until"
                value={until}
                min={from || undefined}
                onChange={(event) => setUntil(event.target.value)}
              />
            </label>
            {mode !== "basic" && (
              <LostTimeInput defaultValue={initialRequest?.filters.lostAt ?? query.get("lostAt") ?? undefined} />
            )}
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <button className="button" type="submit" disabled={searching}>
                <Icon name="search" size={17} />
                {searching ? "Đang tìm kiếm…" : "Tìm kiếm"}
              </button>
              {searching && (
                <button
                  type="button"
                  className="button button-secondary button-danger"
                  onClick={cancelSearch}
                >
                  Hủy
                </button>
              )}
            </div>
          </form>
          <div className="filter-legend">
            <p className="eyebrow">Ba cách nhận lại đồ</p>
            {Object.entries(custodyLabels).map(([key, label]) => (
              <Badge key={key} value={key}>
                {label}
              </Badge>
            ))}
          </div>
        </aside>
        <section aria-label="Kết quả tìm kiếm" aria-busy={loading}>
          <div className="results-heading">
            <h2>
              {request?.files.length
                ? request.text ? "Gợi ý theo ảnh và mô tả" : "Gợi ý theo ảnh món đồ"
                : request?.text || query.get("q")
                  ? `Kết quả cho “${request?.text || query.get("q")}”`
                  : "Kết quả tìm kiếm"}
            </h2>
            {items && (
              <span className="muted">
                {items.length} {request ? "gợi ý" : "món trên trang này"}
              </span>
            )}
          </div>
          {!request && !hasBasicFilters && (
            <EmptyState title="Nhập thông tin món đồ cần tìm" icon="search">
              <p>Thêm mô tả, ảnh, khu vực hoặc khoảng ngày để bắt đầu tìm kiếm.</p>
            </EmptyState>
          )}
          <ErrorNotice error={error} retry={retry} />
          {request && error && (
            <Notice tone="warning">
              <strong>
                {error instanceof ApiError && error.status === 503
                  ? "Tìm kiếm gợi ý tạm thời chưa sẵn sàng."
                  : "Chưa lấy được gợi ý tìm kiếm."}
              </strong>
              <p>Hãy thử lại hoặc điều chỉnh mô tả, ảnh và bộ lọc tìm kiếm.</p>
              {fallback && (
                <a className="text-button" href={fallback}>
                  Dùng bộ lọc cơ bản <Icon name="arrow" size={15} />
                </a>
              )}
            </Notice>
          )}
          {loading && (
            <div style={{ textAlign: "center", padding: "2rem 1rem" }}>
              <Loading />
              {searching && request?.files.length ? (
                <div style={{ marginTop: "1rem" }}>
                  <p style={{ fontWeight: 600, color: "#0f172a" }}>{searchStep}</p>
                  <p style={{ fontSize: "0.875rem", color: "#64748b" }}>
                    Quá trình phân tích hình ảnh AI có thể mất vài giây...
                  </p>
                  <button
                    type="button"
                    className="button button-secondary button-danger button-small"
                    style={{ marginTop: "0.75rem" }}
                    onClick={cancelSearch}
                  >
                    Hủy tìm kiếm
                  </button>
                </div>
              ) : null}
            </div>
          )}
          {suggestions && (
            <Notice>
              <p>
                Thứ tự là gợi ý {suggestions.mode === "combined" ? "theo ảnh và mô tả" : suggestions.mode === "image" ? "theo ảnh" : "theo mô tả"},
                không xác nhận quyền sở hữu.
              </p>
              {suggestions.partial && (
                <p>Một số gợi ý không còn hợp lệ nên danh sách có thể chưa đầy đủ.</p>
              )}
              {suggestions.filtersRelaxed && (
                <p>Chưa có tin đủ phù hợp trong khu vực nên đã tìm thêm ở nơi khác. Tin cùng khu vực vẫn xếp trước; bộ lọc ngày được giữ nguyên.</p>
              )}
              {suggestions.items.length > 0 && fallback && (
                <a className="text-button" href={fallback}>
                  Lọc cơ bản theo khu vực và ngày
                </a>
              )}
            </Notice>
          )}
          {items && (
            <>
              {items.length ? (
                <div className="item-grid">
                  {items.map((item, index) => (
                    <a
                      className="item-card"
                      key={item.id}
                      href={`/items/${item.id}`}
                    >
                      <div className="item-card-image">
                        <ItemPhoto item={item} />
                        <Badge value={item.custody.kind}>
                          {custodyLabels[item.custody.kind]}
                        </Badge>
                      </div>
                      <div className="item-card-body">
                        <span className="eyebrow">
                          {suggestions && `Gợi ý ${suggestions.items[index].rank} · `}
                          {formatDate(item.createdAt)}
                        </span>
                        <h3>{item.title}</h3>
                        <p className="clamp-two">{item.publicDescription}</p>
                        <span className="item-location">
                          <Icon name="pin" size={16} />
                          {item.foundArea}
                        </span>
                        <span className="item-card-action">
                          Xem chi tiết
                          <Icon name="arrow" size={17} />
                        </span>
                      </div>
                    </a>
                  ))}
                </div>
              ) : (
                <EmptyState title="Chưa thấy món đồ phù hợp" icon="search">
                  <p>
                    {request ? "Thử rút gọn mô tả hoặc mở rộng khoảng ngày nhặt được." : "Thử rút gọn từ khóa hoặc mở rộng khu vực và khoảng ngày nhặt được."}
                  </p>
                </EmptyState>
              )}
              {!request && basic.data && (
                <Pagination page={basic.data.page} totalPages={basic.data.totalPages} />
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}

export function ItemDetail({ id }: { id: string }) {
  const resource = useResource<Item>(`/api/items/${id}`);
  const [photo, setPhoto] = useState(0);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const item = resource.data;
  const point = useResource<Point>(
    item?.custody.kind === "point" && item.custody.pointId
      ? `/api/reception-points/${item.custody.pointId}`
      : null,
  );

  useEffect(() => {
    if (!lightboxOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setLightboxOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [lightboxOpen]);
  if (resource.loading) return <Loading />;
  if (!item) {
    if (resource.error instanceof ApiError && resource.error.status === 404) {
      return (
        <EmptyState title="Món đồ không tồn tại hoặc đã được gỡ" icon="document">
          <p>Nội dung này có thể đã được chủ sở hữu gỡ bỏ hoặc liên kết không chính xác.</p>
          <a className="button" href="/">
            Quay về trang chủ
          </a>
        </EmptyState>
      );
    }
    return <ErrorNotice error={resource.error} retry={resource.reload} />;
  }
  const custody = item.custody;
  const address = custody.publicAddress ?? point.data?.publicAddress;
  return (
    <>
      <div className="detail-topline">
        <a className="text-button" href="/search">
          <Icon name="back" size={16} />
          Quay lại tìm kiếm
        </a>
        <Badge value={item.lifecycle} />
      </div>
      {custody.kind !== "person" && (
        <Notice tone={custody.kind === "external" ? "warning" : "info"}>
          <strong>
            {custody.kind === "point"
              ? "Món đồ đang được giữ tại Findie Hub."
              : "Món đồ đang được giữ ngoài hệ thống Findie."}
          </strong>
          <p>
            Vui lòng đến trực tiếp nơi giữ và đối chiếu thông tin để nhận đồ.
          </p>
        </Notice>
      )}
      <div className="detail-layout">
        <div className="detail-main">
          <section className="panel photo-panel">
            <div className="photo-badge">
              <Icon name="shield" size={15} />
              Chỉ hiển thị ảnh đã được duyệt
            </div>
            <div
              style={{
                cursor: item.images[photo]?.url ? "zoom-in" : "default",
                position: "relative",
              }}
              onClick={() => {
                if (item.images[photo]?.url) setLightboxOpen(true);
              }}
              title={
                item.images[photo]?.url ? "Bấm để xem ảnh phóng to" : undefined
              }
            >
              <ItemPhoto item={item} large index={photo} />
            </div>
            {item.images.length > 1 && (
              <div className="photo-thumbnails">
                {item.images.map((image, index) => (
                  <button
                    type="button"
                    key={image.id}
                    onClick={() => setPhoto(index)}
                    aria-label={`Xem ảnh ${index + 1}`}
                    aria-pressed={photo === index}
                  >
                    <ItemPhoto item={item} index={index} />
                  </button>
                ))}
              </div>
            )}
            <div className="photo-caption">
              <span>Mã: {item.id.slice(0, 8)}</span>
              <span>Đăng ngày {formatDate(item.createdAt)}</span>
            </div>
          </section>
          <section className="panel item-description">
            <Badge value={custody.kind}>{custodyLabels[custody.kind]}</Badge>
            <h1>{item.title}</h1>
            <div className="item-facts">
              <div>
                <Icon name="pin" />
                <div>
                  <span>Địa điểm nhặt được</span>
                  <p>{item.foundArea}</p>
                </div>
              </div>
              <div>
                <Icon name="clock" />
                <div>
                  <span>Thời gian nhặt được</span>
                  <p>{foundTime(item)}</p>
                </div>
              </div>
            </div>
            <h2>Mô tả từ người nhặt</h2>
            <p className="preserve-lines">{item.publicDescription}</p>
            <Notice>
              <strong>Giữ lại những chi tiết chỉ chủ sở hữu mới biết.</strong>
              <p>
                Thông tin riêng sẽ được đối chiếu trong yêu cầu nhận đồ hoặc
                trực tiếp khi trao trả.
              </p>
            </Notice>
          </section>
        </div>
        <aside className="detail-aside">
          <section className={`panel custody-panel custody-${custody.kind}`}>
            <span className="custody-icon">
              <Icon
                name={custody.kind === "person" ? "user" : "building"}
                size={27}
              />
            </span>
            <p className="eyebrow">{custodyLabels[custody.kind]}</p>
            <h2>
              {custody.displayName ??
                custody.name ??
                point.data?.name ??
                "Người giữ món đồ"}
            </h2>
            {custody.kind === "person" ? (
              <>
                <p className="muted">
                  Chat được mở sau khi người giữ chấp thuận yêu cầu nhận đồ.
                </p>
                <ol className="timeline">
                  <li>
                    <strong>Gửi yêu cầu nhận đồ</strong>
                    <p>Trả lời các câu hỏi xác minh nếu có.</p>
                  </li>
                  <li>
                    <strong>Chờ người giữ đối chiếu</strong>
                    <p>Người giữ kiểm tra với món đồ thực tế.</p>
                  </li>
                  <li>
                    <strong>Hẹn gặp để trao trả</strong>
                    <p>Chọn địa điểm công cộng và an toàn.</p>
                  </li>
                </ol>
                {item.canClaim && (
                  <a
                    className="button button-wide"
                    href={`/items/${id}/claim`}
                  >
                    <Icon name="lock" size={17} />
                    Gửi yêu cầu nhận đồ
                  </a>
                )}
              </>
            ) : (
              <>
                <ErrorNotice error={point.error} retry={point.reload} />
                {address && (
                  <p className="public-address">
                    <Icon name="pin" />
                    {address}
                  </p>
                )}
                <p className="preserve-lines muted">
                  {custody.instructions ??
                    point.data?.directions ??
                    "Mang theo giấy tờ và thông tin chứng minh quyền sở hữu để đối chiếu tại quầy."}
                </p>
                {address && (
                  <a
                    className="button button-wide"
                    href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Icon name="pin" size={17} />
                    Chỉ đường đến nơi giữ
                  </a>
                )}
                <Notice tone="warning">
                  Việc nhận đồ được xác minh trực tiếp tại quầy, không qua yêu
                  cầu online.
                </Notice>
              </>
            )}
          </section>
          <SafetyNote />
          <a className="hub-callout" href="/hubs">
            <Icon name="building" size={22} />
            <div>
              <strong>Mạng lưới Findie Hub</strong>
              <p>Tìm điểm tiếp nhận trong cộng đồng</p>
            </div>
            <Icon name="arrow" size={17} />
          </a>
        </aside>
      </div>

      {lightboxOpen && item.images[photo]?.url && (
        <div className="lightbox-backdrop" onClick={() => setLightboxOpen(false)}>
          <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="lightbox-close-btn"
              onClick={() => setLightboxOpen(false)}
              aria-label="Đóng ảnh"
            >
              ✕
            </button>
            <img
              src={imageUrl(item.images[photo]?.url)}
              alt={item.title}
            />
            <div
              style={{
                color: "#e2e8f0",
                marginTop: "0.75rem",
                fontSize: "0.875rem",
                textAlign: "center",
              }}
            >
              {item.title} — Ảnh {photo + 1}/{item.images.length} (Bấm Esc hoặc ngoài ảnh để đóng)
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export function Points() {
  const points = useResource<Point[]>("/api/reception-points");
  return (
    <>
      <PageHeader
        eyebrow="Một nơi an tâm để trao trả"
        title="Mạng lưới Findie Hub"
      >
        Tra cứu địa chỉ điểm tiếp nhận đang hoạt động và hướng dẫn bàn giao trực
        tiếp.
      </PageHeader>
      <ErrorNotice error={points.error} retry={points.reload} />
      {points.loading && <Loading />}
      {points.data &&
        (points.data.length ? (
          <div className="points-grid">
            {points.data.map((point) => (
              <article className="panel point-card" key={point.id}>
                <span className="empty-icon">
                  <Icon name="building" size={27} />
                </span>
                <h2>{point.name}</h2>
                <p className="public-address">
                  <Icon name="pin" size={17} />
                  {point.publicAddress}
                </p>
                {point.directions && (
                  <p className="muted preserve-lines">{point.directions}</p>
                )}
                <a
                  className="button button-secondary"
                  target="_blank"
                  rel="noreferrer"
                  href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(point.publicAddress)}`}
                >
                  Xem đường đi
                  <Icon name="arrow" size={16} />
                </a>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="Chưa có điểm tiếp nhận được công bố">
            <p>Vui lòng quay lại sau để xem danh sách điểm đang hoạt động.</p>
          </EmptyState>
        ))}
    </>
  );
}
