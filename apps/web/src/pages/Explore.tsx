import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import {
  ApiError,
  custodyLabels,
  formatDate,
  foundTime,
  pageNumber,
  type Item,
  type Page,
  type Point,
} from "../lib/api";
import { useAction, useResource } from "../hooks/hooks";
import { SearchImages } from "../components/SearchImages";
import { vietnamLocal } from "../lib/itemForm";
import {
  basicSearchUrl,
  searchImages,
  saveSearch,
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

function searchOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
  if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
  event.preventDefault();
  event.currentTarget.form?.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
}

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
              onKeyDown={searchOnEnter}
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
  const searchButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
      const target = event.target;
      if (!(target instanceof HTMLElement) || target.closest("form") !== searchButton.current?.form
        || target.closest("button, a, summary, select, input[type=file], [role=button]")) return;
      event.preventDefault();
      searchButton.current?.click();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
  const query = new URLSearchParams(window.location.search);
  const page = pageNumber(query.get("page"));
  const [mode, setMode] = useState(
    query.get("mode") === "basic" ? "basic" : "text",
  );
  const [files, setFiles] = useState<readonly File[]>(initialRequest?.files ?? []);
  const [from, setFrom] = useState(initialRequest?.filters.from ?? query.get("from") ?? "");
  const [until, setUntil] = useState(initialRequest?.filters.until ?? query.get("until") ?? "");
  const [request, setRequest] = useState<SearchInput | null>(() => {
    if (initialRequest && (initialRequest.text.trim() || initialRequest.files.length)) return initialRequest;
    const text = query.get("q")?.trim();
    return query.get("mode") !== "basic" && text
      ? {
          text,
          files: [],
          filters: {
            area: query.get("area")?.trim() || undefined,
            from: query.get("from") || undefined,
            until: query.get("until") || undefined,
            lostAt: query.get("lostAt") || undefined,
          },
        }
      : null;
  });
  const [formError, setFormError] = useState<Error | null>(null);
  const [suggestions, setSuggestions] = useState<SearchResponse | null>(null);
  const [searchError, setSearchError] = useState<Error | null>(null);
  const [searching, setSearching] = useState(Boolean(request));
  const [attempt, setAttempt] = useState(0);
  const saveAction = useAction();
  const [savedRequest, setSavedRequest] = useState<SearchInput | null>(null);
  const saveKey = useRef<{ request: SearchInput; key: string } | null>(null);
  function trackSearch() {
    if (!request) return;
    const submitted = request;
    if (saveKey.current?.request !== submitted)
      saveKey.current = { request: submitted, key: crypto.randomUUID() };
    const key = saveKey.current.key;
    void saveAction.run(async () => {
      await saveSearch(submitted.files, submitted.text, submitted.filters, key);
      setSavedRequest(submitted);
    });
  }
  const filter = new URLSearchParams({ page: String(page), pageSize: "12" });
  for (const key of ["q", "area", "from", "until"])
    if (query.get(key)?.trim()) filter.set(key, query.get(key)!.trim());
  const hasBasicFilters = query.get("mode") === "basic"
    && ["q", "area", "from", "until"].some((key) => filter.has(key));
  const basic = useResource<Page<Item>>(request || !hasBasicFilters ? null : `/api/items?${filter}`);
  useEffect(() => {
    if ((suggestions || basic.data) && window.matchMedia("(max-width: 850px)").matches)
      document.getElementById("search-results-title")?.focus();
  }, [suggestions, basic.data]);
  useEffect(() => {
    if (!request) return;
    const controller = new AbortController();
    let active = true;
    setSearching(true);
    setSearchError(null);
    setSuggestions(null);
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
        if (active)
          setSearchError(
            cause instanceof Error && !signal.aborted
              ? cause
              : new Error("Máy chủ phản hồi quá lâu. Vui lòng thử lại."),
          );
      })
      .finally(() => {
        if (active) setSearching(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [request, attempt]);
  function submit(event: FormEvent<HTMLFormElement>) {
    const form = new FormData(event.currentTarget);
    const text = String(form.get("q") ?? "").trim();
    if (mode === "basic") {
      if (!["q", "area", "from", "until"].some((key) => String(form.get(key) ?? "").trim())) {
        event.preventDefault();
        setFormError(new Error("Hãy nhập từ khóa, khu vực hoặc khoảng ngày để lọc."));
      }
      return;
    }
    event.preventDefault();
    if (!text && !files.length) {
      setFormError(new Error("Hãy nhập mô tả hoặc chọn từ 1 đến 3 ảnh để tìm kiếm."));
      return;
    }
    setFormError(null);
    saveAction.setError(null);
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
  const activeFilters = request?.filters ?? (hasBasicFilters ? {
    area: query.get("area"), from: query.get("from"), until: query.get("until"),
  } : null);
  return (
    <div className="search-page">
      <PageHeader
        eyebrow="Từng chi tiết, thêm cơ hội tìm lại"
        title="Cùng tìm lại món đồ của bạn."
      >
        Thêm ảnh hoặc vài đặc điểm bạn còn nhớ. Findie sẽ giúp bạn tìm những món đồ phù hợp.
      </PageHeader>
      <div className="search-layout">
        <aside className="panel filter-panel">
          <div className="panel-title">
            <h2>Món đồ bạn cần tìm</h2>
            <a className="text-button" href="/search">
              <Icon name="refresh" size={14} />
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
              <textarea
                id="search-query"
                name="q"
                defaultValue={initialRequest?.text ?? query.get("q") ?? ""}
                maxLength={mode === "basic" ? 200 : 2000}
                rows={3}
                placeholder={mode === "basic" ? "Ví, chìa khóa, balô…" : "Ví dụ: Ví da đen, khóa kéo vàng, bị mất ở phòng E.205…"}
              />
              {mode === "text" && (
                <span className="field-hint">
                  Màu sắc, nhãn hiệu, hình dáng hoặc một chi tiết dễ nhận ra.
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
              {mode !== "basic" && <span className="field-hint">Ưu tiên tìm gần bạn, mở rộng khi chưa có món phù hợp.</span>}
            </label>
            <details className="search-options" open={Boolean(from || until || initialRequest?.filters.lostAt || query.get("lostAt")) || undefined}>
              <summary><Icon name="clock" size={16} /> Thu hẹp theo thời gian</summary>
              <div className="search-date-fields">
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
              </div>
              {mode !== "basic" && (
                <LostTimeInput defaultValue={initialRequest?.filters.lostAt ?? query.get("lostAt") ?? undefined} />
              )}
            </details>
            <button ref={searchButton} className="button" type="submit" disabled={searching}>
              <Icon name="search" size={17} />
              {searching ? "Đang tìm kiếm…" : "Tìm kiếm"}
            </button>
          </form>
          <p className="search-privacy"><Icon name="shield" size={16} /> Ảnh tìm kiếm chỉ dùng để đối chiếu, không đăng công khai.</p>
        </aside>
        <section className="search-results" aria-label="Kết quả tìm kiếm" aria-busy={loading}>
          <div className="results-heading">
            <div>
              <p className="eyebrow">{request || hasBasicFilters ? "Những món đồ có thể bạn đang tìm" : "Hành trình tìm lại bắt đầu ở đây"}</p>
              <h2 id="search-results-title" tabIndex={-1}>
                {request?.files.length
                  ? request.text ? "Gợi ý theo ảnh và mô tả" : "Gợi ý theo ảnh món đồ"
                  : request?.text || (hasBasicFilters && query.get("q"))
                    ? `Kết quả cho “${request?.text || query.get("q")}”`
                    : "Kết quả tìm kiếm"}
              </h2>
            </div>
            {items && (
              <span className="results-count" role="status">
                <strong>{items.length}</strong> {request ? "gợi ý" : "món trên trang này"}
              </span>
            )}
          </div>
          {(request || hasBasicFilters) && <a className="text-button search-edit-link" href="#search-query"><Icon name="search" size={15} /> Sửa tìm kiếm</a>}
          {activeFilters && (activeFilters.area || activeFilters.from || activeFilters.until) && (
            <div className="search-filter-chips" aria-label="Điều kiện đã tìm">
              {activeFilters.area && <span><Icon name="pin" size={14} />{activeFilters.area}</span>}
              {activeFilters.from && <span>Từ {formatDate(activeFilters.from)}</span>}
              {activeFilters.until && <span>Đến {formatDate(activeFilters.until)}</span>}
            </div>
          )}
          {!request && !hasBasicFilters && (
            <div className="search-welcome">
              <EmptyState title="Bạn còn nhớ điều gì về món đồ?" icon="search">
                <p>Một bức ảnh hoặc vài dòng mô tả là đủ để bắt đầu. Kết quả phù hợp sẽ xuất hiện tại đây sau khi bạn tìm kiếm.</p>
                <button className="button button-secondary" type="button" onClick={() => document.getElementById("search-query")?.focus()}>
                  Thêm mô tả <Icon name="arrow" size={16} />
                </button>
              </EmptyState>
              <div className="search-tips">
                <h3>Một chút chi tiết, dễ tìm hơn</h3>
                <p><Icon name="eye" size={18} /><span><strong>Nhớ đặc điểm riêng</strong>Màu sắc, nhãn hiệu và phụ kiện giúp thu hẹp gợi ý.</span></p>
                <p><Icon name="upload" size={18} /><span><strong>Thêm ảnh nếu có</strong>Dùng tối đa 3 góc chụp để đối chiếu rõ hơn.</span></p>
                <p><Icon name="pin" size={18} /><span><strong>Bắt đầu từ nơi bạn làm mất</strong>Thêm khu vực hoặc thời gian để kết quả sát hơn.</span></p>
              </div>
            </div>
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
          {loading && <div className="search-loading"><Loading /><p>Đang đối chiếu những đặc điểm bạn cung cấp…</p></div>}
          {suggestions && (
            <Notice>
              <p>
                Thứ tự là gợi ý {suggestions.mode === "combined" ? "theo ảnh và mô tả" : suggestions.mode === "image" ? "theo ảnh" : "theo mô tả"},
                không xác nhận quyền sở hữu.
              </p>
              {suggestions.partial && (
                <p>Một số gợi ý không còn hợp lệ nên danh sách có thể chưa đầy đủ.</p>
              )}
              {suggestions.rankingMethod === "similarity_fallback" && (
                <p>Kết quả đã được lọc theo độ tương đồng; bước chấm lại nâng cao chưa sẵn sàng.</p>
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
          {request && suggestions && (
            <Notice tone={savedRequest === request ? "success" : "info"}>
              {savedRequest === request ? (
                <p>Đã lưu tin tìm. <a href="/saved-searches">Xem tin tìm và thông báo</a></p>
              ) : (
                <>
                  <strong>Chưa có món đồ phù hợp với bạn?</strong>
                  <p>Theo dõi tìm kiếm này để nhận thông báo khi có món đồ có thể phù hợp. Ảnh gốc không được lưu.</p>
                  <button className="button button-secondary" type="button" disabled={saveAction.busy} onClick={trackSearch}>
                    {saveAction.busy ? "Đang lưu tin tìm…" : "Theo dõi tìm kiếm này"}
                  </button>
                </>
              )}
              <ErrorNotice error={saveAction.error} />
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
                        {suggestions && <span className="search-rank">Gợi ý {suggestions.items[index].rank}</span>}
                        <Badge value={item.custody.kind}>
                          {custodyLabels[item.custody.kind]}
                        </Badge>
                      </div>
                      <div className="item-card-body">
                        <span className="item-found-date"><Icon name="clock" size={14} /> Đăng ngày {formatDate(item.createdAt)}</span>
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
    </div>
  );
}

export function ItemDetail({ id }: { id: string }) {
  const resource = useResource<Item>(`/api/items/${id}`);
  const [photo, setPhoto] = useState(0);
  const item = resource.data;
  const point = useResource<Point>(
    item?.custody.kind === "point" && item.custody.pointId
      ? `/api/reception-points/${item.custody.pointId}`
      : null,
  );
  if (resource.loading) return <Loading />;
  if (!item)
    return <ErrorNotice error={resource.error} retry={resource.reload} />;
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
            <ItemPhoto item={item} large index={photo} />
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
