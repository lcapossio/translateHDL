// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (C) 2026 Leonardo Capossio - bard0 design
// Deliberately BROKEN translation: increments by 2 instead of 1. Used to prove
// the parity ladder actually detects divergence (trace, waveform, and formal
// SEC must all FAIL on this). Do not "fix" it.
`timescale 1ns / 1ps

module counter #(
    parameter WIDTH = 8
) (
    input  wire             clk,
    input  wire             rst,
    input  wire             en,
    output reg  [WIDTH-1:0] count
);
    always @(posedge clk) begin
        if (rst)
            count <= {WIDTH{1'b0}};
        else if (en)
            count <= count + 2'd2;   // BUG: should be +1
    end

    initial count = {WIDTH{1'b0}};
endmodule
