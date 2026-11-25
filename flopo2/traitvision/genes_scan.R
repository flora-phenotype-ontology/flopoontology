# Gene-family size against traits across sequenced plants, with the phylogeny.
#   Rscript flopo2/traitvision/genes_scan.R local-corpora/trait-vision/applications
# Input: genes/gene-species.tsv, genes/families.tsv (species x family protein counts; `genes.py matrix`, written from families.npz).
# For each trait and each family that varies: phylolm(log2(count + 1) ~ trait + log2(proteins) + busco), Pagel's lambda.
# Output: genes/scan.tsv (all tests with Benjamini-Hochberg q per trait), genes/scan-top.tsv.
.libPaths(c("~/tmp/flopo-trait-vision/Rlib", .libPaths()))
suppressMessages({library(ape); library(phylolm); library(parallel)})
A <- commandArgs(trailingOnly = TRUE)[1]
G <- file.path(A, "genes")
s <- read.delim(file.path(G, "gene-species.tsv"), na.strings = "NA", stringsAsFactors = FALSE)
M <- as.matrix(read.delim(file.path(G, "families.tsv"), row.names = 1, check.names = FALSE))
s <- s[!is.na(s$tip), ]
tree <- read.tree(file.path(A, "phylo", "v0.1", "ALLMB.tre"))
tree <- keep.tip(tree, intersect(tree$tip.label, s$tip)); tree <- multi2di(tree, random = FALSE)
tree$edge.length[tree$edge.length < 1e-6] <- 1e-6; tree$node.label <- NULL
s <- s[match(tree$tip.label, s$tip), ]; rownames(s) <- s$tip
M <- M[s$proteome, ]; rownames(M) <- s$tip
s$lp <- as.numeric(scale(log2(s$proteins))); s$busco <- as.numeric(scale(s$busco))
traits <- c("woody", "annual", "hairy", "spiny", "fleshy_fruit", "climber", "succulent", "compound", "toothed", "blue_purple", "yellow", "white",
            "red_orange", "nfix", "c4", "height", "leaf_area", "petal_length", "fruit_length", "seed_length", "n_flowers", "n_stamens")
cat("species", nrow(s), "families", ncol(M), "\n")
res <- list()
for (t in traits) {
  ok <- !is.na(s[[t]])
  bin <- all(s[[t]][ok] %in% c(0, 1))
  if (sum(ok) < 60 || (bin && min(table(s[[t]][ok])) < 12)) { cat(t, "skipped:", sum(ok), "species\n"); next }
  d <- s[ok, ]; tr <- keep.tip(tree, d$tip); d <- d[match(tr$tip.label, d$tip), ]
  d$x <- if (bin) d[[t]] else as.numeric(scale(d[[t]]))
  X <- log2(M[d$tip, ] + 1)
  var <- which(apply(X, 2, function(v) sum(v > 0) >= 0.1 * length(v) && sd(v) > 0.25))
  cat(t, "species", nrow(d), if (bin) paste("with trait", sum(d$x)), "families tested", length(var), "\n")
  r <- mclapply(var, function(j) {
    d$y <- X[, j]
    p <- tryCatch(phylolm(y ~ x + lp + busco, data = d, phy = tr, model = "lambda"), error = function(e) NULL)
    if (is.null(p)) return(NULL)
    k <- summary(p)$coefficients["x", ]
    data.frame(trait = t, family = colnames(X)[j], estimate = k[1], se = k[2], p = k[4], lambda = p$optpar,
               mean_with = if (bin) mean(M[d$tip, j][d$x == 1]) else NA, mean_without = if (bin) mean(M[d$tip, j][d$x == 0]) else NA, species = nrow(d))
  }, mc.cores = 12)
  r <- do.call(rbind, r); r$q <- p.adjust(r$p, "BH"); res[[t]] <- r
  cat("   q < 0.05:", sum(r$q < 0.05), " q < 0.01:", sum(r$q < 0.01), "\n")
}
res <- do.call(rbind, res)
write.table(res, file.path(G, "scan.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)
top <- res[res$q < 0.1, ]; if (nrow(top)) top <- top[order(top$trait, top$p), ]
write.table(top, file.path(G, "scan-top.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)
