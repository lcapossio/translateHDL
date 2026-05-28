// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (C) 2026 Leonardo Capossio - bard0 design
// Reference design for translateHDL self-tests: synchronous up-counter with
// synchronous reset (reset dominates enable).
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
            count <= count + 1'b1;
    end

    initial count = {WIDTH{1'b0}};
endmodule
