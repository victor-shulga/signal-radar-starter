// node site/test.mjs: вхід не пускає без дійсного токена Cloudflare Access.
import assert from 'node:assert';
import { verifyAccess } from './worker.js';
const env = { ACCESS_TEAM_DOMAIN: 't.cloudflareaccess.com', ACCESS_AUD: 'aud1' };
const { publicKey, privateKey } = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const jwk = { ...(await crypto.subtle.exportKey('jwk', publicKey)), kid: 'k1' };
const fetcher = async () => ({ json: async () => ({ keys: [jwk] }) });
const b = o => Buffer.from(typeof o === 'string' ? o : JSON.stringify(o)).toString('base64url');
const sign = async (claims, head = { alg: 'RS256', kid: 'k1' }) => {
  const m = b(head) + '.' + b(claims);
  return m + '.' + Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5', privateKey, new TextEncoder().encode(m))).toString('base64url');
};
const good = { iss: 'https://t.cloudflareaccess.com', aud: ['aud1'], exp: Date.now() / 1000 + 60, email: 'a@yourcompany.com' };
assert.equal(await verifyAccess(await sign(good), env, fetcher), 'a@yourcompany.com');
assert.equal(await verifyAccess(null, env, fetcher), null);
assert.equal(await verifyAccess('junk', env, fetcher), null);
assert.equal(await verifyAccess(await sign({ ...good, aud: ['other'] }), env, fetcher), null);
assert.equal(await verifyAccess(await sign({ ...good, iss: 'https://evil' }), env, fetcher), null);
assert.equal(await verifyAccess(await sign({ ...good, exp: 1 }), env, fetcher), null);
const t = await sign(good); assert.equal(await verifyAccess(t.slice(0, -6) + 'AAAAAA', env, fetcher), null);
const none = b({ alg: 'none', kid: 'k1' }) + '.' + b(good) + '.'; assert.equal(await verifyAccess(none, env, fetcher), null);
console.log('site test ok');
