import assert from "node:assert/strict";
import { afterEach, beforeEach, mock, test } from "node:test";
import { uploadImage } from "./api.ts";
import { prepareImage, validateImages, validatePostImages } from "./images.ts";

const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64");
const webp = [
  "UklGRjwAAABXRUJQVlA4IDAAAADQAwCdASpQADwAPm02mUmkIyKhIagAgA2JaQAADHThw4cOHDhwrAAA/vshgAAAAAA=",
  "UklGRiQAAABXRUJQVlA4TBcAAAAvT8AOAAfQ//73v/8BICH8ny9F9D+1AgA=",
  "UklGRoIAAABXRUJQVlA4WAoAAAAQAAAATwAAOwAAQUxQSBAAAAABB1DAiAgACeH/fCmi/6kVVlA4IEwAAAAwBACdASpQADwAPm02mUmkIyKhIagAgA2JaQB2APwAABtnvSQIECBAgJAA/vCbQ//+QXLC65Gv//yA/5Af8gP/498W46IviEAAAAAA",
].map((value) => Buffer.from(value, "base64"));
const originalDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
const originalDecoder = Object.getOwnPropertyDescriptor(globalThis, "createImageBitmap");
let width: number, height: number, decodes: number, closes: number;
let encoded: Blob | null;
let drawn: unknown[];
let context: { fillStyle: string; fillRect: (...args: unknown[]) => void; drawImage: (...args: unknown[]) => void };
let canvas: { width: number; height: number; getContext: () => typeof context | null; toBlob: (callback: BlobCallback, type: string, quality: number) => void };

beforeEach(() => {
  width = 3200; height = 2400; decodes = 0; closes = 0;
  encoded = new Blob(["jpeg"], { type: "image/jpeg" });
  drawn = [];
  context = {
    fillStyle: "",
    fillRect(...args) { assert.deepEqual(args, [0, 0, canvas.width, canvas.height]); },
    drawImage(...args) { drawn = args; assert.equal(context.fillStyle, "white"); },
  };
  canvas = {
    width: 0, height: 0,
    getContext: () => context,
    toBlob(callback, type, quality) {
      assert.equal(type, "image/jpeg");
      assert.equal(quality, 0.92);
      assert.equal(closes, decodes, "release the source bitmap before encoding");
      callback(encoded);
    },
  };
  Object.defineProperty(globalThis, "createImageBitmap", {
    configurable: true, writable: true,
    value: async (_file: File, options: ImageBitmapOptions) => {
      decodes++;
      assert.equal(options.imageOrientation, "from-image");
      return { width, height, close() { closes++; } };
    },
  });
  Object.defineProperty(globalThis, "document", {
    configurable: true, value: { createElement: () => canvas },
  });
});

afterEach(() => {
  mock.restoreAll();
  if (originalDocument) Object.defineProperty(globalThis, "document", originalDocument);
  else Reflect.deleteProperty(globalThis, "document");
  if (originalDecoder) Object.defineProperty(globalThis, "createImageBitmap", originalDecoder);
  else Reflect.deleteProperty(globalThis, "createImageBitmap");
});

const file = (bytes = png, type = "image/png") => new File([bytes], "source", { type });

test("found-item posts require one to three images while optional selections can stay empty", () => {
  validateImages([]);
  assert.throws(() => validatePostImages([]), /ít nhất 1 ảnh/);
  validatePostImages([file()]);
  validatePostImages(Array(3).fill(file()));
  assert.throws(() => validatePostImages([file(png, "text/plain")]), /JPEG, PNG hoặc WebP/);
  assert.throws(() => validatePostImages(Array(4).fill(file())), /tối đa 3 ảnh/);
});

test("preparation caps either orientation at 1600px without cropping or upscaling", async () => {
  for (const [w, h, expected] of [
    [3200, 2400, [1600, 1200]], [2400, 3200, [1200, 1600]], [80, 60, [80, 60]],
  ] as const) {
    width = w; height = h;
    assert.equal(await prepareImage(file()), encoded);
    assert.deepEqual([canvas.width, canvas.height], expected);
    assert.deepEqual(drawn.slice(1), [0, 0, ...expected]);
  }
  assert.equal(closes, 3);
});

test("already small files keep original bytes when recompression would be larger", async () => {
  width = 80; height = 60;
  encoded = new Blob([new Uint8Array(png.length + 1)], { type: "image/jpeg" });
  const source = file();
  assert.equal(await prepareImage(source), source);
  width = 3200;
  assert.equal(await prepareImage(file()), encoded, "large dimensions must still be reduced");
});

test("JPEG SOF and all WebP dimension variants are accepted before native decoding", async () => {
  // The mock decoder isolates header validation; real browser decoding is checked separately.
  const jpegHeader = Buffer.from([255, 216, 255, 224, 0, 2, 255, 192, 0, 8, 8, 0, 60, 0, 80, 0]);
  await prepareImage(file(jpegHeader, "image/jpeg"));
  for (const bytes of webp) await prepareImage(file(bytes, "image/webp"));
  assert.equal(decodes, 4);
});

test("oversized dimensions, spoofed formats, malformed chunks and animations fail before decoding", async () => {
  for (const [w, h] of [[10001, 1], [7000, 6000], [0, 60]]) {
    const huge = Buffer.from(png);
    huge.writeUInt32BE(w, 16); huge.writeUInt32BE(h, 20);
    await assert.rejects(prepareImage(file(huge)), /10000 px/);
  }
  const animatedPng = Buffer.concat([png.subarray(0, 33), Buffer.from([0, 0, 0, 0, 97, 99, 84, 76, 0, 0, 0, 0]), png.subarray(33)]);
  const animatedWebp = Buffer.from(webp[2]);
  animatedWebp[20] |= 2;
  for (const source of [file(animatedPng), file(animatedWebp, "image/webp")])
    await assert.rejects(prepareImage(source), /ảnh tĩnh/);
  for (const source of [file(Buffer.from("<svg/>")), file(png, "image/jpeg"), file(png.subarray(0, 40)), file(Buffer.from([255, 216, 255, 224, 255, 255]), "image/jpeg")])
    await assert.rejects(prepareImage(source), /không hợp lệ/);
  assert.equal(decodes, 0);
});

test("decode, canvas and encode failures stop preparation and allow retry", async () => {
  const source = file();
  mock.method(globalThis, "createImageBitmap", async () => { throw new Error("decode failed"); });
  await assert.rejects(prepareImage(source), /Không đọc được ảnh/);
  mock.restoreAll();
  canvas.getContext = () => null;
  await assert.rejects(prepareImage(source), /trình duyệt này/);
  assert.equal(closes, 1);
  canvas.getContext = () => context;
  encoded = null;
  await assert.rejects(prepareImage(source), /Không thể thu nhỏ ảnh/);
  assert.equal(closes, 2);
  encoded = new Blob(["jpeg"], { type: "image/jpeg" });
  assert.equal(await prepareImage(source), encoded);
  assert.equal(closes, 3);
});

test("uncertain upload retries reuse encoded bytes, MIME and idempotency key", async () => {
  const source = file();
  const requests: RequestInit[] = [];
  const timeouts = mock.method(AbortSignal, "timeout", () => new AbortController().signal);
  mock.method(globalThis, "fetch", async (path: string, init?: RequestInit) => {
    if (path === "/api/auth/csrf") return Response.json({ token: "csrf-upload" });
    assert.equal(path, "/api/items/item-id/images?position=2");
    requests.push(init!);
    if (requests.length === 1) throw new TypeError("connection lost after commit");
    return Response.json({ id: "saved-once" });
  });
  await assert.rejects(uploadImage("item-id", source, 2));
  await uploadImage("item-id", source, 2);
  assert.equal(decodes, 1);
  assert.equal(requests[0].body, encoded);
  assert.equal(requests[0].body, requests[1].body);
  assert.deepEqual(requests[0].headers, requests[1].headers);
  assert.equal((requests[0].headers as Record<string, string>)["Content-Type"], "image/jpeg");
  assert.equal(requests[0].credentials, "same-origin");
  assert.equal(timeouts.mock.calls.filter(call => call.arguments[0] === 660000).length, 2);
  await uploadImage("item-id", source, 2);
  assert.notEqual((requests[1].headers as Record<string, string>)["Idempotency-Key"],
    (requests[2].headers as Record<string, string>)["Idempotency-Key"]);
});
