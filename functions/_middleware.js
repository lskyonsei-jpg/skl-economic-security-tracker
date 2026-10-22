// SKL Economic Security Tracker - 비밀번호를 통과하지 못하면 아무것도 내보내지 않는다.
const OWNER = "skl";

function unauthorized(message) {
  return new Response(message, {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="SKL Economic Security Tracker", charset="UTF-8"',
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

// 글자를 하나씩 비교하다 틀린 곳에서 멈추면 응답 시간으로 비밀번호를 캐낼 수
// 있다. 길이가 같으면 끝까지 다 보고 판정한다.
function safeEqual(a, b) {
  const enc = new TextEncoder();
  const left = enc.encode(a);
  const right = enc.encode(b);
  if (left.length !== right.length) return false;
  let diff = 0;
  for (let i = 0; i < left.length; i++) diff |= left[i] ^ right[i];
  return diff === 0;
}

// SHA-256 을 16진수 글자로. 소금을 앞에 붙여 같은 비밀번호라도 사람마다
// 다른 해시가 나오게 한다.
async function hashPassword(salt, password) {
  const bytes = new TextEncoder().encode(salt + ":" + password);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// SITE_USERS 한 줄 = `아이디:소금:해시`. 빈 줄과 # 로 시작하는 줄은 건너뛴다.
function parseUsers(raw) {
  const out = new Map();
  for (const line of (raw || "").split(/[\r\n]+/)) {
    const row = line.trim();
    if (!row || row.startsWith("#")) continue;
    const parts = row.split(":");
    if (parts.length !== 3) continue;
    const [name, salt, hash] = parts.map((p) => p.trim());
    if (name && salt && hash) out.set(name, { salt, hash });
  }
  return out;
}

export async function onRequest(context) {
  const { request, env, next } = context;
  // trim: 저장 경로가 값 끝에 줄바꿈을 붙이는 사고가 있었다. 비밀번호에는
  // 공백을 못 쓰게 막아뒀으므로 잘라내도 잃는 것이 없다.
  const ownerPassword = (env.SITE_PASSWORD || "").trim();
  const users = parseUsers(env.SITE_USERS);

  // 아무 계정도 없으면 열어두지 않고 막는다.
  if (!ownerPassword && users.size === 0) {
    return new Response(
      "비밀번호가 아직 설정되지 않았습니다. 사이트_설정.cmd 를 실행해 [2] 를 골라 주세요.",
      { status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } }
    );
  }

  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Basic ")) return unauthorized("로그인이 필요합니다.");

  let decoded;
  try {
    decoded = atob(header.slice(6));
  } catch (error) {
    return unauthorized("로그인이 필요합니다.");
  }

  const split = decoded.indexOf(":");
  const user = split < 0 ? "" : decoded.slice(0, split);
  const pass = split < 0 ? "" : decoded.slice(split + 1);

  // 없는 아이디라도 해시를 한 번 돌린다. 안 돌리면 응답이 빨라져서
  // "이 아이디는 있다/없다"가 밖에서 보인다.
  const found = users.get(user);
  const salt = found ? found.salt : "dummy";
  const hash = await hashPassword(salt, pass);

  let ok = false;
  if (found) {
    ok = safeEqual(hash, found.hash);
  } else if (ownerPassword) {
    // 옛 방식. 아이디 skl 하나에 원문 비밀번호를 맞춰 본다.
    ok = safeEqual(user, OWNER) && safeEqual(pass, ownerPassword);
  }
  if (!ok) return unauthorized("아이디 또는 비밀번호가 맞지 않습니다.");

  const response = await next();
  const out = new Response(response.body, response);
  out.headers.set("Cache-Control", "no-store");
  out.headers.set("X-Robots-Tag", "noindex, nofollow");
  return out;
}
