// RentShield AI - C++ image fingerprint engine
// Perceptual hashing (pHash + dHash) and a fast Hamming-distance index,
// exposed to Python through pybind11 as `rentshield_core`.

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdint>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace py = pybind11;

namespace {

constexpr int kPhashSize = 32;  // input image is 32x32 grayscale
constexpr int kLowFreq = 8;     // keep the 8x8 low-frequency DCT block

// Precomputed DCT-II cosine table: cos[(2x+1) * u * pi / (2N)]
struct DctTable {
    double c[kLowFreq][kPhashSize];
    DctTable() {
        for (int u = 0; u < kLowFreq; ++u)
            for (int x = 0; x < kPhashSize; ++x)
                c[u][x] = std::cos((2.0 * x + 1.0) * u * M_PI / (2.0 * kPhashSize));
    }
};
const DctTable kDct;

inline int popcount64(uint64_t v) { return std::popcount(v); }

}  // namespace

// pHash: 2D DCT of a 32x32 grayscale image, threshold the 8x8 low-frequency
// block (excluding the DC term) against its median -> 64-bit fingerprint.
uint64_t phash(py::array_t<double, py::array::c_style | py::array::forcecast> img) {
    auto buf = img.unchecked<2>();
    if (buf.shape(0) != kPhashSize || buf.shape(1) != kPhashSize)
        throw std::invalid_argument("phash expects a 32x32 grayscale array");

    // Separable DCT: rows first (only 8 output freqs), then columns.
    double rows[kPhashSize][kLowFreq];
    for (int y = 0; y < kPhashSize; ++y)
        for (int u = 0; u < kLowFreq; ++u) {
            double s = 0.0;
            for (int x = 0; x < kPhashSize; ++x) s += buf(y, x) * kDct.c[u][x];
            rows[y][u] = s;
        }
    double coeff[kLowFreq * kLowFreq];
    for (int v = 0; v < kLowFreq; ++v)
        for (int u = 0; u < kLowFreq; ++u) {
            double s = 0.0;
            for (int y = 0; y < kPhashSize; ++y) s += rows[y][u] * kDct.c[v][y];
            coeff[v * kLowFreq + u] = s;
        }

    // Median of the 63 AC coefficients (skip DC at index 0).
    std::vector<double> ac(coeff + 1, coeff + kLowFreq * kLowFreq);
    std::nth_element(ac.begin(), ac.begin() + ac.size() / 2, ac.end());
    const double median = ac[ac.size() / 2];

    uint64_t hash = 0;
    for (int i = 0; i < kLowFreq * kLowFreq; ++i)
        if (coeff[i] > median) hash |= (uint64_t{1} << i);
    return hash;
}

// dHash: compare horizontally adjacent pixels of a 8x9 (rows x cols) image.
uint64_t dhash(py::array_t<double, py::array::c_style | py::array::forcecast> img) {
    auto buf = img.unchecked<2>();
    if (buf.shape(0) != 8 || buf.shape(1) != 9)
        throw std::invalid_argument("dhash expects an 8x9 grayscale array");
    uint64_t hash = 0;
    int bit = 0;
    for (int y = 0; y < 8; ++y)
        for (int x = 0; x < 8; ++x, ++bit)
            if (buf(y, x + 1) > buf(y, x)) hash |= (uint64_t{1} << bit);
    return hash;
}

int hamming(uint64_t a, uint64_t b) { return popcount64(a ^ b); }

struct Match {
    std::string listing_id;
    std::string image_id;
    int phash_distance;
    int dhash_distance;
    double similarity;  // 0..1
};

// In-memory fingerprint index. Each image can hold several hash variants
// (full frame + center crops) so cropped re-uploads still match.
class ImageIndex {
public:
    void add(const std::string& listing_id, const std::string& image_id,
             const std::vector<uint64_t>& phashes, const std::vector<uint64_t>& dhashes) {
        if (phashes.empty() || phashes.size() != dhashes.size())
            throw std::invalid_argument("phashes and dhashes must be non-empty and equal length");
        std::unique_lock lock(mu_);
        for (size_t i = 0; i < phashes.size(); ++i)
            entries_.push_back({listing_id, image_id, phashes[i], dhashes[i]});
        images_[image_id] = listing_id;
    }

    // Return the best match per image whose combined distance is under the threshold.
    std::vector<Match> query(const std::vector<uint64_t>& phashes,
                             const std::vector<uint64_t>& dhashes,
                             int max_distance, const std::string& exclude_listing) const {
        if (phashes.size() != dhashes.size())
            throw std::invalid_argument("phashes and dhashes must be equal length");
        std::shared_lock lock(mu_);
        std::unordered_map<std::string, Match> best;
        for (const auto& e : entries_) {
            if (!exclude_listing.empty() && e.listing_id == exclude_listing) continue;
            for (size_t i = 0; i < phashes.size(); ++i) {
                const int dp = popcount64(e.phash ^ phashes[i]);
                if (dp > max_distance) continue;
                const int dd = popcount64(e.dhash ^ dhashes[i]);
                // pHash is the primary signal; dHash confirms.
                const double score = 1.0 - (0.7 * dp + 0.3 * dd) / 64.0;
                auto it = best.find(e.image_id);
                if (it == best.end() || score > it->second.similarity)
                    best[e.image_id] = {e.listing_id, e.image_id, dp, dd, score};
            }
        }
        std::vector<Match> out;
        out.reserve(best.size());
        for (auto& [_, m] : best) out.push_back(m);
        std::sort(out.begin(), out.end(),
                  [](const Match& a, const Match& b) { return a.similarity > b.similarity; });
        return out;
    }

    size_t size() const {
        std::shared_lock lock(mu_);
        return images_.size();
    }

    void clear() {
        std::unique_lock lock(mu_);
        entries_.clear();
        images_.clear();
    }

private:
    struct Entry {
        std::string listing_id;
        std::string image_id;
        uint64_t phash;
        uint64_t dhash;
    };
    mutable std::shared_mutex mu_;
    std::vector<Entry> entries_;
    std::unordered_map<std::string, std::string> images_;
};

PYBIND11_MODULE(rentshield_core, m) {
    m.doc() = "RentShield AI C++ core: perceptual hashing + similarity index";

    m.def("phash", &phash, py::arg("gray32"), "DCT perceptual hash of a 32x32 grayscale array");
    m.def("dhash", &dhash, py::arg("gray8x9"), "Difference hash of an 8x9 grayscale array");
    m.def("hamming", &hamming, py::arg("a"), py::arg("b"), "Hamming distance between two hashes");

    py::class_<Match>(m, "Match")
        .def_readonly("listing_id", &Match::listing_id)
        .def_readonly("image_id", &Match::image_id)
        .def_readonly("phash_distance", &Match::phash_distance)
        .def_readonly("dhash_distance", &Match::dhash_distance)
        .def_readonly("similarity", &Match::similarity);

    py::class_<ImageIndex>(m, "ImageIndex")
        .def(py::init<>())
        .def("add", &ImageIndex::add, py::arg("listing_id"), py::arg("image_id"),
             py::arg("phashes"), py::arg("dhashes"))
        .def("query", &ImageIndex::query, py::arg("phashes"), py::arg("dhashes"),
             py::arg("max_distance") = 12, py::arg("exclude_listing") = "",
             py::call_guard<py::gil_scoped_release>())
        .def("size", &ImageIndex::size)
        .def("clear", &ImageIndex::clear);
}
