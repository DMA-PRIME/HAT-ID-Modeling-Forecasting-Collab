#!/usr/bin/env Rscript
# Thin bridge between the MCP server and the external forecastEvalReport package.
# The package remains outside this small repository; this script only adapts the
# submitted paths and calls the package's existing JSON/CSV export functions.

args <- commandArgs(trailingOnly = TRUE)

if (length(args) < 6L) {
  stop(
    paste(
      "Usage:",
      "Rscript forecast_eval_adapter.R package_dir options_file forecast_file",
      "truth_file output_dir period [evaluation_model_file] [crosswalk_file]"
    ),
    call. = FALSE
  )
}

package_dir <- normalizePath(args[[1]], mustWork = TRUE, winslash = "/")
options_file <- normalizePath(args[[2]], mustWork = TRUE, winslash = "/")
forecast_file <- normalizePath(args[[3]], mustWork = TRUE, winslash = "/")
truth_file <- normalizePath(args[[4]], mustWork = TRUE, winslash = "/")
output_dir <- args[[5]]
period <- tolower(args[[6]])
evaluation_model_file <- if (length(args) >= 7L && nzchar(args[[7]])) args[[7]] else NULL
crosswalk_file <- if (length(args) >= 8L && nzchar(args[[8]])) args[[8]] else NULL

if (!dir.exists(output_dir) && !dir.create(output_dir, recursive = TRUE)) {
  stop("Could not create the evaluation output directory: ", output_dir, call. = FALSE)
}
output_dir <- normalizePath(output_dir, mustWork = TRUE, winslash = "/")

if (!file.exists(file.path(package_dir, "DESCRIPTION"))) {
  stop("package_dir must point to the forecastEvalReport source directory.", call. = FALSE)
}
if (!period %in% c("realtime", "testing")) {
  stop("period must be 'realtime' or 'testing'.", call. = FALSE)
}
if (!requireNamespace("forecastEvalReport", quietly = TRUE)) {
  stop(
    paste(
      "The forecastEvalReport R package is not installed or its dependencies are missing.",
      "Install it once with:",
      paste0("R CMD INSTALL ", shQuote(package_dir)),
      "Then run this tool again."
    ),
    call. = FALSE
  )
}
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("The R package jsonlite is required to save the adapter result.", call. = FALSE)
}

# Resolve the crosswalk from an explicit argument or the options file. Colleague
# options files often contain an old absolute path, so a same-named local file
# beside the options file is accepted as a portable fallback.
source_env <- new.env(parent = baseenv())
tryCatch(
  source(options_file, local = source_env),
  error = function(error) {
    stop("Could not read the options file: ", conditionMessage(error), call. = FALSE)
  }
)
if (!exists("report_options", envir = source_env)) {
  stop("The options file must define a `report_options` list.", call. = FALSE)
}
report_options <- get("report_options", envir = source_env)
if (!is.list(report_options)) {
  stop("`report_options` must be a list.", call. = FALSE)
}

if (is.null(crosswalk_file)) {
  original_crosswalk <- report_options$variables.crosswalk.file
  if (!is.null(original_crosswalk) && length(original_crosswalk) == 1L &&
      !is.na(original_crosswalk) && nzchar(original_crosswalk)) {
    crosswalk_file <- original_crosswalk
    if (!file.exists(crosswalk_file)) {
      crosswalk_name <- sub("^.*[/\\\\]", "", original_crosswalk)
      crosswalk_file <- file.path(dirname(options_file), crosswalk_name)
    }
  }
}
if (is.null(crosswalk_file) || !file.exists(crosswalk_file)) {
  stop(
    paste(
      "A completed variables crosswalk CSV is required.",
      "Pass crosswalk_file to the MCP tool or place the crosswalk beside the options file."
    ),
    call. = FALSE
  )
}
crosswalk_file <- normalizePath(crosswalk_file, mustWork = TRUE, winslash = "/")

# The external package expects these paths in its standard options structure.
# The temporary options file lets the caller submit a different model/truth pair
# without changing the colleague's original configuration file.
report_options$implementation.model.file <- forecast_file
report_options$outcome.data <- truth_file
report_options$base.box <- output_dir
report_options$variables.crosswalk.file <- crosswalk_file
if (!is.null(evaluation_model_file)) {
  evaluation_model_file <- normalizePath(evaluation_model_file, mustWork = TRUE, winslash = "/")
  report_options$evaluation.model.file <- evaluation_model_file
}

temporary_options <- file.path(output_dir, "forecast_review_options.R")
temporary_options_text <- paste(
  "report_options <-",
  paste(capture.output(dput(report_options)), collapse = "\n")
)
writeLines(temporary_options_text, temporary_options, useBytes = TRUE)

if (period == "realtime") {
  result <- forecastEvalReport::export_realtime_evaluation(
    temporary_options,
    output_dir = output_dir,
    file_prefix = "forecast_review_realtime",
    ai_form = TRUE,
    save_json = TRUE,
    save_results = TRUE,
    quiet = TRUE,
    archive_current = TRUE
  )
} else {
  result <- forecastEvalReport::export_testing_evaluation(
    temporary_options,
    output_dir = output_dir,
    file_prefix = "forecast_review_testing",
    ai_form = TRUE,
    save_json = TRUE,
    save_results = TRUE,
    quiet = TRUE
  )
}

paths <- result$paths
if (is.null(paths)) paths <- list()
paths <- lapply(paths, function(path) {
  if (length(path) == 0L || is.na(path)) return(NULL)
  normalizePath(path, mustWork = FALSE, winslash = "/")
})

manifest <- list(
  method = "forecastEvalReport",
  package_dir = package_dir,
  package_version = as.character(utils::packageVersion("forecastEvalReport")),
  options_file = options_file,
  forecast_file = forecast_file,
  truth_file = truth_file,
  period = period,
  output_dir = output_dir,
  paths = paths
)
jsonlite::write_json(
  manifest,
  file.path(output_dir, "adapter_result.json"),
  auto_unbox = TRUE,
  pretty = TRUE,
  null = "null"
)
unlink(temporary_options)
