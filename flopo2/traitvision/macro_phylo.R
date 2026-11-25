# Phylogenetic regressions on the species table of `macro.py table` (tree: Smith and Brown 2018, ALLMB).
#   Rscript flopo2/traitvision/macro_phylo.R local-corpora/trait-vision/applications
# Continuous responses: phylolm with Pagel's lambda. Binary responses: phyloglm (logistic_MPLE). Climate and sizes are z-scored
# within each model's species, so estimates are per standard deviation. Output: macro-phylo.tsv.
.libPaths(c("~/tmp/flopo-trait-vision/Rlib", .libPaths()))
suppressMessages({library(ape); library(phylolm); library(parallel)})
args <- commandArgs(trailingOnly = TRUE); A <- args[1]; SET <- if (length(args) > 1) args[2] else "main"
d0 <- read.delim(file.path(A, "species-traits.tsv"), na.strings = "NA", stringsAsFactors = FALSE, quote = "")
d0 <- d0[!is.na(d0$tip) & !is.na(d0$mat) & !duplicated(d0$tip), ]
d0$growth[is.na(d0$growth)] <- "unknown"
d0$woody <- ifelse(d0$growth == "woody", 1, ifelse(d0$growth == "herb", 0, NA))
tree <- read.tree(file.path(A, "phylo", "v0.1", "ALLMB.tre"))
models <- list(
  c("flower size and climate", "petal_length ~ mat + logmap + srad + elev + growth + height", "lm"),
  c("flower diameter and climate", "flower_diameter ~ mat + logmap + srad + elev + growth + height", "lm"),
  c("flower size and number", "n_flowers ~ petal_length + height + growth", "lm"),
  c("flower size and number, with climate", "n_flowers ~ petal_length + height + growth + mat + logmap", "lm"),
  c("flower size and leaf size", "petal_length ~ leaf_area + height + growth", "lm"),
  c("flower size and seed size", "petal_length ~ seed_length + height + growth", "lm"),
  c("stamen number and flower size", "n_stamens ~ petal_length + growth", "lm"),
  c("seed size and climate", "seed_length ~ mat + logmap + growth + height", "lm"),
  c("fruit size and climate", "fruit_length ~ mat + logmap + growth + height", "lm"),
  c("leaf area and climate", "leaf_area ~ mat + logmap + growth + height", "lm"),
  c("height and climate", "height ~ mat + logmap + growth", "lm"),
  c("hairy leaves and climate", "hairy ~ mat + logmap + srad + elev + growth", "glm"),
  c("fleshy fruit and climate", "fleshy_fruit ~ mat + logmap + growth", "glm"),
  c("annual and climate", "annual ~ mat + logmap", "glm"),
  c("succulent leaves and climate", "succulent ~ mat + logmap + growth", "glm"),
  c("climber and climate", "climber ~ mat + logmap", "glm"))
# second set: sexual system (5,758 species with one stated system) and checks of the flower size results; fourth element: subset
if (SET == "flowers") models <- list(
  c("dioecy and woody habit", "dioecious ~ woody", "glm"),
  c("dioecy and fleshy fruit", "dioecious ~ fleshy_fruit + woody", "glm"),
  c("dioecy and pale flowers", "dioecious ~ pale_flower + woody", "glm"),
  c("dioecy and climate", "dioecious ~ mat + logmap + woody", "glm"),
  c("dioecy and flower size", "petal_length ~ dioecious + woody + height", "lm"),
  c("dioecy and seed size", "seed_length ~ dioecious + woody + height", "lm"),
  c("flower diameter and number", "n_flowers ~ flower_diameter + height + growth", "lm"),
  c("flower size and number, herbs", "n_flowers ~ petal_length + height", "lm", "growth == 'herb'"),
  c("flower size and number, woody", "n_flowers ~ petal_length + height", "lm", "growth == 'woody'"),
  c("flower size and number, more than one flower", "n_flowers ~ petal_length + height + growth", "lm", "n_flowers > 0"),
  c("flower size and number, leaf area in the model", "n_flowers ~ petal_length + leaf_area + height + growth", "lm"),
  c("flower size and height, herbs", "petal_length ~ height", "lm", "growth == 'herb'"),
  c("flower size and height, woody", "petal_length ~ height", "lm", "growth == 'woody'"),
  c("hairy leaves, herbs", "hairy ~ mat + logmap + elev", "glm", "growth == 'herb'"),
  c("hairy leaves, woody", "hairy ~ mat + logmap + elev", "glm", "growth == 'woody'"))
one <- function(m) {
  f <- as.formula(m[2]); v <- all.vars(f)
  d <- d0[complete.cases(d0[, v]), ]
  if (length(m) > 3) d <- d[eval(parse(text = m[4]), d), ]
  if ("growth" %in% v) d$growth <- relevel(factor(d$growth), "herb")
  tr <- keep.tip(tree, intersect(tree$tip.label, d$tip)); tr <- multi2di(tr, random = FALSE)
  tr$edge.length[tr$edge.length < 1e-6] <- 1e-6; tr$node.label <- NULL
  d <- d[match(tr$tip.label, d$tip), ]; rownames(d) <- d$tip
  num <- setdiff(v, c("growth", "woody", "dioecious", "fleshy_fruit", "pale_flower", if (m[3] == "glm") v[1]))
  for (k in num) d[[k]] <- as.numeric(scale(d[[k]]))
  out <- list()
  if (m[3] == "lm") {
    out[["no phylogeny"]] <- summary(lm(f, data = d))$coefficients[, c(1, 2, 4)]
    p <- tryCatch(phylolm(f, data = d, phy = tr, model = "lambda"), error = function(e) e)
    if (!inherits(p, "error")) out[[sprintf("phylogenetic (lambda %.2f)", p$optpar)]] <- summary(p)$coefficients[, c(1, 2, 4)]
  } else {
    out[["no phylogeny"]] <- summary(glm(f, data = d, family = binomial))$coefficients[, c(1, 2, 4)]
    p <- tryCatch(phyloglm(f, data = d, phy = tr, method = "logistic_MPLE", btol = 30, log.alpha.bound = 6), error = function(e) e)
    if (!inherits(p, "error")) out[[sprintf("phylogenetic (alpha %.3g)", p$alpha)]] <- summary(p)$coefficients[, c(1, 2, 4)]
  }
  if (inherits(p, "error")) cat(m[1], "failed:", conditionMessage(p), "\n")
  do.call(rbind, lapply(names(out), function(k) data.frame(test = m[1], model = k, term = rownames(out[[k]]), estimate = out[[k]][, 1],
                                                            se = out[[k]][, 2], p = out[[k]][, 3], species = nrow(d), row.names = NULL)))
}
res <- do.call(rbind, mclapply(models, one, mc.cores = 8))
write.table(res, file.path(A, if (SET == "main") "macro-phylo.tsv" else paste0("macro-phylo-", SET, ".tsv")), sep = "\t", quote = FALSE, row.names = FALSE)
options(width = 200)
print(res[!grepl("Intercept|growth", res$term), ], digits = 3, row.names = FALSE)
