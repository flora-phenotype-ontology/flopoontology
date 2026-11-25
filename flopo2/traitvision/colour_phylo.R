# Flower colour against the climate of the species' range, with the phylogeny (Smith and Brown 2018, ALLMB) and growth form.
# Input: colour-species.tsv of `applications.py colour-data`. Output: colour-phylo.tsv.
#   Rscript flopo2/traitvision/colour_phylo.R local-corpora/trait-vision/applications [N species, 0 = all]
.libPaths(c("~/tmp/flopo-trait-vision/Rlib", .libPaths()))
suppressMessages({library(ape); library(phylolm); library(parallel)})
args <- commandArgs(trailingOnly = TRUE)
A <- args[1]; N <- if (length(args) > 1) as.integer(args[2]) else 0
COR <- length(args) > 2    # third argument: only species with a stated corolla shape, corolla (tube / open / mixed) as a covariate
d <- read.delim(file.path(A, "colour-species.tsv"), na.strings = "NA", stringsAsFactors = FALSE, quote = "")
d <- d[!is.na(d$tip) & !is.na(d$mat) & d$wind == 0, ]
d <- d[!duplicated(d$tip), ]
if (COR) { d <- d[!is.na(d$corolla), ]; d$corolla <- relevel(factor(d$corolla), "open") }
d$growth[is.na(d$growth)] <- "unknown"
d$growth <- relevel(factor(d$growth), "herb")
set.seed(1)
if (N > 0 && N < nrow(d)) d <- d[sample(nrow(d), N), ]
tr <- read.tree(file.path(A, "phylo", "v0.1", "ALLMB.tre"))
tr <- keep.tip(tr, intersect(tr$tip.label, d$tip))
tr <- multi2di(tr, random = FALSE)
tr$edge.length[tr$edge.length < 1e-6] <- 1e-6
tr$node.label <- NULL
d <- d[match(tr$tip.label, d$tip), ]
rownames(d) <- d$tip
for (k in c("mat", "logmap", "elev", "srad")) d[[k]] <- as.numeric(scale(d[[k]]))
cat("species", nrow(d), "\n")
cols <- c("blue", "purple", "pink", "red", "orange", "yellow", "white", "green")
one <- function(col) {
  f <- as.formula(paste(col, "~ mat + logmap + elev + srad + growth", if (COR) "+ corolla" else ""))
  out <- list()
  g <- summary(glm(f, data = d, family = binomial))$coefficients
  out[["logistic, no phylogeny"]] <- g[, c(1, 2, 4)]
  p <- tryCatch(phyloglm(f, data = d, phy = tr, method = "logistic_MPLE", btol = 30, log.alpha.bound = 6), error = function(e) e)
  if (!inherits(p, "error")) { s <- summary(p)$coefficients; out[[sprintf("phylogenetic logistic (alpha %.3g)", p$alpha)]] <- s[, c(1, 2, 4)] }
  else cat(col, "phyloglm failed:", conditionMessage(p), "\n")
  l <- tryCatch(phylolm(f, data = d, phy = tr, model = "lambda"), error = function(e) e)
  if (!inherits(l, "error")) { s <- summary(l)$coefficients; out[[sprintf("phylogenetic linear (lambda %.2f)", l$optpar)]] <- s[, c(1, 2, 4)] }
  else cat(col, "phylolm failed:", conditionMessage(l), "\n")
  do.call(rbind, lapply(names(out), function(m) data.frame(colour = col, model = m, term = rownames(out[[m]]), estimate = out[[m]][, 1], se = out[[m]][, 2], p = out[[m]][, 3],
                                                             share = mean(d[[col]]), species = nrow(d), row.names = NULL)))
}
res <- do.call(rbind, mclapply(cols, one, mc.cores = 8))
write.table(res, file.path(A, sprintf("colour-phylo%s%s.tsv", if (N > 0) paste0("-", N) else "", if (COR) "-corolla" else "")), sep = "\t", quote = FALSE, row.names = FALSE)
print(res[res$term %in% c("mat", "logmap", "elev", "srad", "corollatube"), ], digits = 3, row.names = FALSE)
