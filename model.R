# Minimal file-based model boundary for later R integration.
# Usage: Rscript model.R input.csv forecast.csv
args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("Usage: Rscript model.R input.csv forecast.csv")
input <- read.csv(args[[1]], stringsAsFactors = FALSE)
if (!all(c("date", "value") %in% names(input))) stop("Input CSV must contain date and value columns")
if (nrow(input) < 2) stop("At least 2 observations are required")
forecast <- data.frame(date = input$date, actual = input$value, forecast = rep(tail(input$value, 1), nrow(input)))
write.csv(forecast, args[[2]], row.names = FALSE)
