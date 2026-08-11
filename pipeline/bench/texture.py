"""Is region density predictable from a cheap texture proxy, and does escalating
flatten strength actually tame the pathological case?"""

import time

import cv2
import numpy as np

from pbn import images, preprocess

K = 16


def region_count(img):
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    Z = lab.reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, lb, _ = cv2.kmeans(Z, K, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    q = lb.reshape(img.shape[:2]).astype(np.int32)
    return sum(
        max(0, cv2.connectedComponents((q == i).astype(np.uint8), 8)[0] - 1) for i in range(K)
    )


def lapvar(img):
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


print(f"{'image':22s} {'MP':>6s} {'lapvar':>8s} {'dens/MP':>9s}")
print("-" * 50)
rows = []
for p in images.list_images("../corpus/dev"):
    img = images.fit_long_edge(images.load(p), 1400)
    mp = img.shape[0] * img.shape[1] / 1e6
    f = preprocess.flatten(img, 1.0, "bilateral")
    d = region_count(f) / mp
    lv = lapvar(img)
    rows.append((p.stem, lv, d))
    print(f"{p.stem:22s} {mp:6.2f} {lv:8.1f} {d:9,.0f}")

r = np.corrcoef([x[1] for x in rows], [x[2] for x in rows])[0, 1]
rs = np.corrcoef(
    np.argsort(np.argsort([x[1] for x in rows])), np.argsort(np.argsort([x[2] for x in rows]))
)[0, 1]
print(f"\ncorrelation lapvar vs density: pearson {r:.3f}  spearman {rs:.3f}")

print("\n" + "=" * 50)
print("ESCALATING STRENGTH on the pathological image (fetched_hires_c)")
print(f"{'strength':>9s} {'dens/MP':>9s} {'time':>7s}")
print("-" * 30)
img = images.fit_long_edge(images.load("../corpus/dev/fetched_hires_c.jpg"), 1400)
mp = img.shape[0] * img.shape[1] / 1e6
for s in (1.0, 2.0, 3.0, 4.0, 6.0):
    t = time.time()
    f = preprocess.flatten(img, s, "bilateral")
    el = time.time() - t
    print(f"{s:9.1f} {region_count(f) / mp:9,.0f} {el:6.2f}s")

print("\nSame on a well-behaved image (portrait), to check we don't over-flatten it:")
img2 = images.fit_long_edge(images.load("../corpus/dev/builtin_portrait.png"), 1400)
mp2 = img2.shape[0] * img2.shape[1] / 1e6
for s in (1.0, 2.0, 3.0, 4.0, 6.0):
    f = preprocess.flatten(img2, s, "bilateral")
    print(f"{s:9.1f} {region_count(f) / mp2:9,.0f}")

print("\n" + "=" * 50)
print("PROXY CHECK: is density at 400px a usable predictor of density at 1400px?")
print(f"{'image':22s} {'400px':>9s} {'1400px':>9s} {'ratio':>7s}")
print("-" * 50)
for p in images.list_images("../corpus/dev"):
    full = images.fit_long_edge(images.load(p), 1400)
    proxy = images.fit_long_edge(images.load(p), 400)
    df = region_count(preprocess.flatten(full, 1.0, "bilateral")) / (
        full.shape[0] * full.shape[1] / 1e6
    )
    dp = region_count(preprocess.flatten(proxy, 1.0, "bilateral")) / (
        proxy.shape[0] * proxy.shape[1] / 1e6
    )
    print(f"{p.stem:22s} {dp:9,.0f} {df:9,.0f} {df / dp:6.2f}x")
