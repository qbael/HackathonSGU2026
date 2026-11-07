import { useState } from "react";
import { updateProfile, type UserProfile } from "../lib/auth";
import { formatDate } from "../lib/api";
import { useAction } from "../hooks/hooks";
import { ErrorNotice, Icon, Notice, PageHeader } from "../components/ui";

export default function Profile({ user, onUpdate }: {
  user: UserProfile;
  onUpdate: (profile: UserProfile) => void;
}) {
  const [name, setName] = useState(user.displayName);
  const [saved, setSaved] = useState(false);
  const action = useAction();
  return <>
    <PageHeader eyebrow="Tài khoản Google của bạn" title="Hồ sơ cá nhân">
      Tên hiển thị giúp người trao đổi nhận ra bạn trong quá trình tìm và trả đồ.
    </PageHeader>
    <form className="panel claim-form form-stack" onSubmit={async (event) => {
      event.preventDefault();
      setSaved(false);
      const profile = await action.run(() => updateProfile(name));
      if (profile) {
        onUpdate(profile);
        setName(profile.displayName);
        setSaved(true);
      }
    }}>
      <label htmlFor="display-name">Tên hiển thị
      <input id="display-name" value={name} required maxLength={120}
        disabled={action.busy} onChange={(event) => {
          setName(event.target.value);
          setSaved(false);
        }} />
      </label>
      <p className="muted">Email: {user.email ?? "Chưa có email"}</p>
      <p className="field-hint">Tham gia ngày {formatDate(user.createdAt)}</p>
      <ErrorNotice error={action.error} />
      {saved && <Notice tone="success">Đã cập nhật hồ sơ của bạn.</Notice>}
      <div className="form-actions">
        <button className="button" disabled={action.busy || !name.trim()}>
          <Icon name="check" size={17} />
          {action.busy ? "Đang lưu…" : "Lưu hồ sơ"}
        </button>
      </div>
    </form>
  </>;
}
