import { useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { loginApi, me, changePassword, getApiUrl, setApiUrl } from "../lib/api";
import { useAuth } from "../context/AuthContext";

const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const from = (location.state as any)?.from?.pathname || "/live";
  const [form, setForm] = useState({ login: "", password: "" });
  const [totpCode, setTotpCode] = useState("");
  const [totpRequired, setTotpRequired] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastCreds, setLastCreds] = useState<{ login: string; password: string } | null>(null);

  // Change password modal
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [tempToken, setTempToken] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await loginApi(form.login, form.password);
      if (res.must_change_password) {
        setTempToken(res.access_token);
        setMustChangePassword(true);
        setLastCreds({ login: form.login, password: form.password });
        return;
      }
      const profile = await me(res.access_token);
      login(res.access_token, profile);
      nav(from, { replace: true });
    } catch (err: any) {
      if (err?.status === 400 && String(err?.message || "").toLowerCase().includes("totp")) {
        setTotpRequired(true);
        setLastCreds({ login: form.login, password: form.password });
      } else {
        setError(err?.message || "Ошибка входа");
      }
    } finally {
      setLoading(false);
    }
  };

  const submitTotp = async () => {
    if (!lastCreds) return;
    setLoading(true);
    setError(null);
    try {
      const res = await loginApi(lastCreds.login, lastCreds.password, totpCode || undefined);
      if (res.must_change_password) {
        setTempToken(res.access_token);
        setMustChangePassword(true);
        setTotpRequired(false);
        return;
      }
      const profile = await me(res.access_token);
      login(res.access_token, profile);
      nav(from, { replace: true });
    } catch (err: any) {
      setError(err?.message || "Ошибка входа (TOTP)");
    } finally {
      setLoading(false);
      setTotpRequired(false);
      setTotpCode("");
    }
  };

  const handleChangePassword = async () => {
    if (!tempToken || !lastCreds) return;
    if (newPassword.length < 6) {
      setError("Пароль должен быть не менее 6 символов");
      return;
    }
    if (newPassword !== newPasswordConfirm) {
      setError("Пароли не совпадают");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await changePassword(tempToken, lastCreds.password, newPassword);
      // Re-login with new password
      const res = await loginApi(lastCreds.login, newPassword);
      const profile = await me(res.access_token);
      login(res.access_token, profile);
      nav(from, { replace: true });
    } catch (err: any) {
      setError(err?.message || "Ошибка смены пароля");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="shell" style={{ maxWidth: 420 }}>
      <div className="card" style={{ marginTop: 60 }}>
        <h2 className="title">Вход в систему</h2>
        <p className="muted" style={{ marginBottom: 16 }}>
          Введите логин и пароль.
        </p>
        <form className="stack" onSubmit={handleSubmit}>
          <label className="field">
            <span className="label">Логин</span>
            <input
              className="input"
              value={form.login}
              onChange={(e) => setForm({ ...form, login: e.target.value })}
              required
              autoFocus
            />
          </label>
          <label className="field">
            <span className="label">Пароль</span>
            <input
              className="input"
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              required
            />
          </label>
          {error && !mustChangePassword && <div className="danger">{error}</div>}
          <button className="btn" type="submit" disabled={loading}>
            {loading ? "Входим..." : "Войти"}
          </button>
        </form>
        <details style={{ marginTop: 12 }}>
          <summary className="muted" style={{ cursor: "pointer" }}>Настройка сервера</summary>
          <div className="field" style={{ marginTop: 8 }}>
            <span className="label">URL сервера</span>
            <input
              className="input"
              defaultValue={getApiUrl()}
              placeholder="https://cctv.example.com"
              onBlur={(e) => {
                const val = e.target.value.trim();
                if (val && val !== getApiUrl()) setApiUrl(val);
              }}
            />
            <span className="muted" style={{ fontSize: 12 }}>
              Укажите адрес вашего CCTV-сервера
            </span>
          </div>
        </details>
      </div>

      {totpRequired && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3 style={{ marginTop: 0 }}>Введите TOTP</h3>
            <p className="muted">Введите код из приложения.</p>
            <div className="field" style={{ marginTop: 8 }}>
              <span className="label">TOTP код</span>
              <input
                className="input"
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                placeholder="123456"
              />
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" onClick={submitTotp} disabled={loading}>Подтвердить</button>
              <button className="btn secondary" onClick={() => setTotpRequired(false)}>Отмена</button>
            </div>
          </div>
        </div>
      )}

      {mustChangePassword && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3 style={{ marginTop: 0 }}>Смена пароля</h3>
            <p className="muted">Необходимо сменить пароль при первом входе.</p>
            <div className="stack" style={{ marginTop: 8 }}>
              <label className="field">
                <span className="label">Новый пароль</span>
                <input
                  className="input"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="label">Подтверждение</span>
                <input
                  className="input"
                  type="password"
                  value={newPasswordConfirm}
                  onChange={(e) => setNewPasswordConfirm(e.target.value)}
                />
              </label>
              {error && <div className="danger">{error}</div>}
            </div>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" onClick={handleChangePassword} disabled={loading || !newPassword}>
                Сменить пароль
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default LoginPage;
