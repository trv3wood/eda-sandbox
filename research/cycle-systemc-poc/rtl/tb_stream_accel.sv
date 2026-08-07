module tb_stream_accel;
  logic clk = 0;
  logic reset_n = 0;
  logic start = 0;
  logic [7:0] length = 0;
  logic [15:0] scale = 0;
  logic [15:0] bias = 0;
  logic in_valid = 0;
  logic in_ready;
  logic [15:0] in_data = 0;
  logic out_valid;
  logic out_ready = 0;
  logic [31:0] result;

  stream_accel dut(.*);
  always #5 clk = ~clk;

  task automatic send(input logic [15:0] value);
    begin
      @(negedge clk);
      while (!in_ready) @(negedge clk);
      in_valid = 1;
      in_data = value;
      @(posedge clk);
      @(negedge clk);
      in_valid = 0;
    end
  endtask

  initial begin
    repeat (2) @(negedge clk);
    reset_n = 1;
    length = 3;
    scale = 2;
    bias = 3;
    start = 1;
    @(negedge clk);
    start = 0;
    send(5);
    send(7);
    send(11);
    wait(out_valid);
    if (result !== 32'd55)
      $fatal(1, "result=%0d expected=55", result);
    repeat (2) begin
      @(posedge clk);
      if (!out_valid || result !== 32'd55)
        $fatal(1, "output did not remain stable under backpressure");
    end
    @(negedge clk);
    out_ready = 1;
    @(posedge clk);
    @(negedge clk);
    if (out_valid)
      $fatal(1, "out_valid did not clear after handshake");
    $display("stream_accel result=%0d PASS", result);
    $finish;
  end
endmodule
