import { useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { changePassword, getApiUrl, loginApi, me, setApiUrl } from "../lib/api";

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
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [tempToken, setTempToken] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await loginApi(form.login, form.password);
      if (response.must_change_password) {
        setTempToken(response.access_token);
        setMustChangePassword(true);
        setLastCreds({ login: form.login, password: form.password });
        return;
      }
      const profile = await me(response.access_token);
      login(response.access_token, profile);
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
      const response = await loginApi(lastCreds.login, lastCreds.password, totpCode || undefined);
      if (response.must_change_password) {
        setTempToken(response.access_token);
        setMustChangePassword(true);
        setTotpRequired(false);
        return;
      }
      const profile = await me(response.access_token);
      login(response.access_token, profile);
      nav(from, { replace: true });
    } catch (err: any) {
      setError(err?.message || "Ошибка двухфакторной авторизации");
    } finally {
      setLoading(false);
      setTotpRequired(false);
      setTotpCode("");
    }
  };

  const handleChangePassword = async () => {
    if (!tempToken || !lastCreds) return;
    if (newPassword.length < 6) {
      setError("Новый пароль должен быть не менее 6 символов");
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
      const response = await loginApi(lastCreds.login, newPassword);
      const profile = await me(response.access_token);
      login(response.access_token, profile);
      nav(from, { replace: true });
    } catch (err: any) {
      setError(err?.message || "Ошибка смены пароля");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-shell auth-shell--simple">
      <section className="auth-panel auth-panel--form auth-panel--solo">
        <div className="stack" style={{ gap: 6 }}>
          <span className="pill">CCTV Console</span>
          <h1 className="title" style={{ margin: 0 }}>Вход в систему</h1>
        </div>

        <form className="stack" onSubmit={handleSubmit}>
          <label className="field">
            <span className="label">Логин</span>
            <input
              className="input"
              value={form.login}
              onChange={(event) => setForm({ ...form, login: event.target.value })}
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
              onChange={(event) => setForm({ ...form, password: event.target.value })}
              required
            />
          </label>
          {error && !mustChangePassword && <div className="danger">{error}</div>}
          <button className="btn" type="submit" disabled={loading}>
            {loading ? "Вход..." : "Войти"}
          </button>
        </form>

        <details className="auth-advanced">
          <summary className="muted">Параметры сервера</summary>
          <div className="field" style={{ marginTop: 12 }}>
            <span className="label">URL backend</span>
            <input
              className="input"
              defaultValue={getApiUrl()}
              placeholder="https://cctv.example.com"
              onBlur={(event) => {
                const value = event.target.value.trim();
                if (value && value !== getApiUrl()) {
                  setApiUrl(value);
                }
              }}
            />
          </div>
        </details>
      </section>

      {totpRequired && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3 style={{ marginTop: 0 }}>Введите двухфакторный код авторизации</h3>
            <p className="muted">Введите код из приложения-аутентификатора.</p>
            <div className="field" style={{ marginTop: 8 }}>
              <span className="label">Двухфакторный код</span>
              <input
                className="input"
                value={totpCode}
                onChange={(event) => setTotpCode(event.target.value)}
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
            <p className="muted">Необходимо указать новый пароль для входа в систему.</p>
            <div className="stack" style={{ marginTop: 8 }}>
              <label className="field">
                <span className="label">Новый пароль</span>
                <input className="input" type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
              </label>
              <label className="field">
                <span className="label">Подтверждение</span>
                <input className="input" type="password" value={newPasswordConfirm} onChange={(event) => setNewPasswordConfirm(event.target.value)} />
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
